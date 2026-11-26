#!/usr/bin/env python3
"""预载整组知识卡的本地复习页；点击反馈直接切换，后台保存到原批次和卡库。"""
import argparse
from contextlib import redirect_stdout
from datetime import datetime
import hashlib
import importlib.util
import io
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import secrets
import sys
from types import SimpleNamespace
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('recall_fsrs', Path(__file__).with_name('fsrs_review.py'))
fsrs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fsrs)


def review_state(cards, batch_path):
    with fsrs.cards_lock(str(cards)):
        batch = fsrs.load_batch(batch_path, cards)
        card_records = fsrs.sync_batch(cards, batch)
        retention_percent = fsrs.read_retention(cards)
    ready = [fsrs.display_card(c, i+1, len(batch['cards'])) for i, c in enumerate(batch['cards'])]
    ratings = [{'card_id': e['card_id'], 'rating': e['rating'], 'due': e['after']['due']} for e in batch['events']]
    ids = {card['id'] for card in ready}
    scheduling = {card['id']: card for card in card_records if card['id'] in ids}
    return {'version': 1, 'batch_id': batch['id'], 'cards': ready, 'completed': len(ratings),
            'ratings': ratings, 'scheduling': scheduling, 'retention_percent': retention_percent}


def render_page(state, batch_path, timezone, token=''):
    template = (Path(__file__).parent.parent/'assets/recall.html').read_text(encoding='utf-8')
    identity = f"{Path(batch_path).resolve()}:{state['batch_id']}"
    payload = {'mode': 'server' if token else 'offline',
               'workspace_id': hashlib.sha256(identity.encode()).hexdigest(),
               'timezone': timezone, 'initial_state': state}
    boot = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c')
    return template.replace('__REVIEW_TOKEN__', token).replace('__REVIEW_BOOT__', boot)


def make_server(cards, batch_path, port=0, timezone=None):
    cards, batch_path = Path(cards).resolve(), Path(batch_path).resolve()
    token = secrets.token_urlsafe(24)
    zone = ZoneInfo(timezone) if timezone else None

    def state():
        return review_state(cards, batch_path)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send(self, status, body, mime='application/json; charset=utf-8'):
            data = body.encode('utf-8') if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; object-src 'none'; frame-ancestors 'self'")
            self.end_headers()
            self.wfile.write(data)

        def permitted(self):
            host = self.headers.get('Host', '')
            return host in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

        def do_GET(self):
            if not self.permitted():
                return self.send(403, {'error': '仅支持本机访问'})
            path = urlparse(self.path).path
            try:
                if path == '/':
                    page = render_page(state(), batch_path, timezone, token)
                    return self.send(200, page, 'text/html; charset=utf-8')
                if path == '/api/state':
                    return self.send(200, state())
                if path == '/api/health':
                    return self.send(200, {'status': 'ok'})
                self.send(404, {'error': '页面不存在'})
            except (OSError, ValueError, KeyError, TypeError, SystemExit) as exc:
                self.send(409, {'error': str(exc)})

        def do_POST(self):
            if not self.permitted() or self.headers.get('X-Review-Session') != token:
                return self.send(403, {'error': '请从本机复习页提交反馈'})
            origin = self.headers.get('Origin')
            allowed = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
            if origin and origin not in allowed:
                return self.send(403, {'error': '请求来源不匹配'})
            path = urlparse(self.path).path
            if path not in ('/api/rate', '/api/repeat', '/api/retention'):
                return self.send(404, {'error': '接口不存在'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 2048:
                    raise ValueError('反馈长度无效')
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError('请求格式无效')
                if path == '/api/retention':
                    with fsrs.cards_lock(str(cards)):
                        fsrs.write_retention(cards, request.get('retention_percent'))
                    return self.send(200, {'state': state()})
                today = datetime.now(zone).date().isoformat() if zone else datetime.now().astimezone().date().isoformat()
                if path == '/api/repeat':
                    with fsrs.cards_lock(str(cards)):
                        batch = fsrs.load_batch(batch_path, cards)
                        if len(batch['events']) == len(batch['cards']):
                            prepared = batch_path.parent/'repeat-prepared.json'
                            fsrs.save_batch(prepared, batch['cards'])
                            args = SimpleNamespace(file=str(cards), batch=str(batch_path), input=str(prepared), date=today)
                            with redirect_stdout(io.StringIO()):
                                fsrs.cmd_prepare(args)
                    return self.send(200, {'state': state()})
                if type(request.get('rating')) is not int or request['rating'] not in range(1, 5):
                    raise ValueError('反馈应为四档之一')
                if not isinstance(request.get('card_id'), str):
                    raise ValueError('卡片编号无效')
                args = SimpleNamespace(file=str(cards), batch=str(batch_path), card_id=request['card_id'], rating=request['rating'], date=today)
                with fsrs.cards_lock(str(cards)), redirect_stdout(io.StringIO()) as output:
                    active = fsrs.load_batch(batch_path, cards)
                    if request.get('batch_id') != active['id']:
                        raise ValueError('复习组已切换，请刷新页面后继续')
                    fsrs.cmd_batch_rate(args)
                result = json.loads(output.getvalue())
                self.send(200, {'result': result, 'state': state()})
            except (OSError, ValueError, KeyError, TypeError, SystemExit) as exc:
                self.send(409, {'error': str(exc)})

    server = HTTPServer(('127.0.0.1', port), Handler)
    state()  # 启动前核对批次，失败不展示空壳页。
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cards', required=True)
    parser.add_argument('--batch', required=True)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--timezone')
    parser.add_argument('--url-file')
    parser.add_argument('--export-html', type=Path, help='导出独立 HTML，无需启动本机服务')
    args = parser.parse_args()
    if args.export_html:
        if args.timezone:
            ZoneInfo(args.timezone)
        if args.export_html.suffix.lower() != '.html':
            parser.error('导出路径需使用 .html 扩展名')
        page = render_page(review_state(args.cards, args.batch), args.batch, args.timezone)
        args.export_html.parent.mkdir(parents=True, exist_ok=True)
        args.export_html.write_text(page, encoding='utf-8')
        return
    server = make_server(args.cards, args.batch, args.port, args.timezone)
    url = f'http://127.0.0.1:{server.server_port}/'
    if args.url_file:
        Path(args.url_file).write_text(url+'\n', encoding='utf-8')
    print('READY '+url, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
