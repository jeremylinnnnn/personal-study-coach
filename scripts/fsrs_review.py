#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fsrs_review.py — 个人自学教练的复习卡片调度器（FSRS-6，日粒度简化版）

算法与 open-spaced-repetition/py-fsrs 6.3.3 同公式；面向"每日一次学习会话"场景
做日粒度简化：无分钟级 learning/relearning 步骤，不启用随机 fuzz（保证可复现）。

评分映射：1=重来 2=困难 3=良好 4=简单

用法:
  fsrs_review.py add   CARDS --title TEXT [--cue TEXT] [--knowledge-id ID] [--tags A,B]
  fsrs_review.py show  CARDS [--date YYYY-MM-DD] [--all]
  fsrs_review.py rate  CARDS CARD_ID RATING [--date YYYY-MM-DD]
  fsrs_review.py stats CARDS [--date YYYY-MM-DD] [--days N]
  fsrs_review.py prepare CARDS --batch BATCH --input PREPARED_JSON [--date YYYY-MM-DD]
  fsrs_review.py batch-next CARDS --batch BATCH
  fsrs_review.py batch-rate CARDS CARD_ID RATING --batch BATCH [--date YYYY-MM-DD]

cards.jsonl 每行一张卡；调度字段（stability/difficulty/due/last_review/reps/
lapses/history/state）由本脚本独占维护，其他字段在更新时原样保留。
"""

import argparse
from contextlib import contextmanager
from copy import deepcopy
import json
import math
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

# ---- FSRS-6 默认参数（与 py-fsrs 6.3.3 DEFAULT_PARAMETERS 一致） ----
WEIGHTS = (
    0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194, 0.001,
    1.8722, 0.1666, 0.796, 1.4835, 0.0614, 0.2629, 1.6483, 0.6014,
    1.8729, 0.5425, 0.0912, 0.0658, 0.1542,
)
DECAY = -WEIGHTS[20]
FACTOR = 0.9 ** (1.0 / DECAY) - 1
DESIRED_RETENTION = 0.9
RETENTION_PRESETS = (90, 95)
MAX_INTERVAL = 365
STABILITY_MIN = 0.001

RATING_LABELS = {1: "重来", 2: "困难", 3: "良好", 4: "简单"}

SCHEDULING_FIELDS = (
    "state", "stability", "difficulty", "due",
    "last_review", "reps", "lapses", "history",
)


# ---- FSRS 核心公式（照抄 py-fsrs 6.3.3，仅做日粒度简化） ----

def clamp_difficulty(d):
    return min(max(d, 1.0), 10.0)


def clamp_stability(s):
    return max(s, STABILITY_MIN)


def initial_stability(rating):
    return clamp_stability(WEIGHTS[rating - 1])


def initial_difficulty(rating, clamp=True):
    d = WEIGHTS[4] - math.exp(WEIGHTS[5] * (rating - 1)) + 1
    return clamp_difficulty(d) if clamp else d


def retrievability(elapsed_days, stability):
    t = max(0, elapsed_days)
    return (1.0 + FACTOR * t / stability) ** DECAY


def next_interval(stability, desired_retention=DESIRED_RETENTION):
    ivl = (stability / FACTOR) * (desired_retention ** (1.0 / DECAY) - 1)
    return min(max(round(ivl), 1), MAX_INTERVAL)


def next_recall_stability(stability, difficulty, r, rating):
    hard_penalty = WEIGHTS[15] if rating == 2 else 1.0
    easy_bonus = WEIGHTS[16] if rating == 4 else 1.0
    s = stability * (
        1.0
        + math.exp(WEIGHTS[8])
        * (11.0 - difficulty)
        * (stability ** -WEIGHTS[9])
        * (math.exp((1.0 - r) * WEIGHTS[10]) - 1.0)
        * hard_penalty
        * easy_bonus
    )
    return clamp_stability(s)


def next_forget_stability(stability, difficulty, r):
    long_term = (
        WEIGHTS[11]
        * (difficulty ** -WEIGHTS[12])
        * (((stability + 1.0) ** WEIGHTS[13]) - 1.0)
        * math.exp((1.0 - r) * WEIGHTS[14])
    )
    short_term = stability / math.exp(WEIGHTS[17] * WEIGHTS[18])
    return clamp_stability(min(long_term, short_term))


def short_term_stability(stability, rating):
    increase = (
        math.exp(WEIGHTS[17] * (rating - 3.0 + WEIGHTS[18]))
        * (stability ** -WEIGHTS[19])
    )
    if rating >= 2:
        increase = max(increase, 1.0)
    return clamp_stability(stability * increase)


def next_difficulty(difficulty, rating):
    delta = -(WEIGHTS[6] * (rating - 3.0))
    arg2 = difficulty + (10.0 - difficulty) * delta / 9.0     # 线性阻尼
    arg1 = initial_difficulty(4, clamp=False)                  # 均值回归目标
    return clamp_difficulty(WEIGHTS[7] * arg1 + (1.0 - WEIGHTS[7]) * arg2)


# ---- 调度（日粒度） ----

def schedule(card, rating, today, desired_retention=DESIRED_RETENTION):
    """按评分更新一张卡片的 FSRS 状态，返回 (旧稳定度, 旧难度, 回忆率或 None)。"""
    old_s = card.get("stability")
    old_d = card.get("difficulty")
    last_raw = card.get("last_review")
    last = date.fromisoformat(last_raw) if last_raw else None
    elapsed = (today - last).days if last else None

    r_now = None
    if card.get("state") != "review" or old_s is None or last is None:
        new_s = initial_stability(rating)
        new_d = initial_difficulty(rating)
    elif elapsed <= 0:
        # 与 py-fsrs 一致：间隔不足 1 天（含日期回拨）走短期稳定性
        new_s = short_term_stability(old_s, rating)
        new_d = next_difficulty(old_d, rating)
    else:
        r_now = retrievability(elapsed, old_s)
        if rating == 1:
            new_s = next_forget_stability(old_s, old_d, r_now)
        else:
            new_s = next_recall_stability(old_s, old_d, r_now, rating)
        new_d = next_difficulty(old_d, rating)

    ivl = next_interval(new_s, desired_retention)
    card["state"] = "review"
    card["stability"] = round(new_s, 4)
    card["difficulty"] = round(new_d, 4)
    card["due"] = (today + timedelta(days=ivl)).isoformat()
    card["last_review"] = today.isoformat()
    card["reps"] = int(card.get("reps") or 0) + 1
    if rating == 1:
        card["lapses"] = int(card.get("lapses") or 0) + 1
    history = card.get("history")
    if not isinstance(history, list):
        history = []
    event = {"date": today.isoformat(), "rating": rating}
    if desired_retention != DESIRED_RETENTION:
        event["retention_percent"] = round(desired_retention * 100)
    history.append(event)
    card["history"] = history
    return old_s, old_d, r_now, ivl


# ---- 文件读写 ----

def load_cards(path):
    """读取 JSONL；返回 (卡片列表, 损坏行列表[(行号, 原文, 错误)])。"""
    cards, bad = [], []
    if not os.path.exists(path):
        return [], []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if not isinstance(obj, dict) or "id" not in obj:
                    raise ValueError("缺少 id 字段")
                cards.append(obj)
            except Exception as exc:  # noqa: BLE001
                bad.append((lineno, line, str(exc)))
    return cards, bad


def load_cards_for_update(path):
    """写入前检查损坏行，发现问题时保留原文件并停止操作。"""
    cards, bad = load_cards(path)
    if bad:
        line_numbers = ", ".join(str(lineno) for lineno, _, _ in bad)
        raise SystemExit(
            "卡片库存在损坏数据，第 %s 行。已停止写入，请先备份并修复原文件。"
            % line_numbers
        )
    return cards


def save_cards(path, cards):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".cards-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for card in cards:
                f.write(json.dumps(card, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def find_card(cards, card_id):
    for card in cards:
        if str(card.get("id")) == str(card_id):
            return card
    return None


def parse_date(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise SystemExit("日期格式应为 YYYY-MM-DD：%r" % text)


def parse_tags(text):
    if not text:
        return []
    return [t.strip() for t in text.split(",") if t.strip()]


def next_auto_id(cards):
    max_num = 0
    for card in cards:
        m = re.match(r"^C-(\d+)$", str(card.get("id", "")))
        if m:
            max_num = max(max_num, int(m.group(1)))
    return "C-%03d" % (max_num + 1)


# ---- 先整组准备，再逐张呈现；批次同时是未完成写入的恢复日志 ----

@contextmanager
def cards_lock(path):
    lock = os.path.abspath(path) + ".lock"
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise SystemExit("知识卡库正在写入或存在遗留锁；先确认任务状态，不覆盖锁")
    try:
        os.close(fd)
        yield
    finally:
        os.unlink(lock)


def save_batch(path, batch):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".recall-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(batch, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_batch(path, cards_path):
    with open(path, encoding="utf-8") as stream:
        batch = json.load(stream)
    if not isinstance(batch, dict) or batch.get("version") != 1:
        raise SystemExit("回忆批次结构损坏，保留原文件后检查")
    stored_path = batch.get("cards_path")
    if not isinstance(stored_path, str):
        raise SystemExit("回忆批次缺少卡库路径")
    if not os.path.isabs(stored_path):
        stored_path = os.path.join(os.path.dirname(os.path.abspath(path)), stored_path)
    if os.path.abspath(stored_path) != os.path.abspath(cards_path):
        raise SystemExit("批次与知识卡库不匹配，不能混用工作区")
    cards, events = batch.get("cards"), batch.get("events")
    if not isinstance(cards, list) or not 1 <= len(cards) <= 10 or not isinstance(events, list) or len(events) > len(cards):
        raise SystemExit("回忆批次卡片或进度损坏")
    ids = [c.get("id") for c in cards if isinstance(c, dict)]
    if len(ids) != len(cards) or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
        raise SystemExit("回忆批次卡片编号缺失或重复")
    for number, event in enumerate(events):
        if not isinstance(event, dict) or event.get("card_id") != cards[number]["id"] or event.get("rating") not in RATING_LABELS:
            raise SystemExit("回忆批次评分顺序损坏")
        if not isinstance(event.get("before"), dict) or not isinstance(event.get("after"), dict):
            raise SystemExit("回忆批次恢复记录损坏")
    return batch


def sync_batch(cards_path, batch):
    """批次先持久化，卡库随后同步；中断后根据事件编号重放，避免重复计分。"""
    cards = load_cards_for_update(cards_path)
    ids = [c["id"] for c in cards]
    if len(set(ids)) != len(ids):
        raise SystemExit("知识卡库编号重复，停止批次写入")
    before = deepcopy(cards)
    for prepared in batch["cards"]:
        current = find_card(cards, prepared["id"])
        if current is None:
            cards.append(deepcopy(prepared))
            continue
        known_id = current.get("knowledge_id")
        if known_id and known_id != prepared["knowledge_id"]:
            raise SystemExit("知识点编号冲突，停止同步批次")
        for field in ("kind", "knowledge_id", "title", "cue", "focus", "prepared_explanation", "source"):
            current[field] = prepared[field]
        current["content"] = prepared.get("content") or prepared["prepared_explanation"]
    for event in batch["events"]:
        current = find_card(cards, event["card_id"])
        if any(h.get("batch_event_id") == event["event_id"] for h in current.get("history", []) if isinstance(h, dict)):
            continue
        existing = {field: current.get(field) for field in SCHEDULING_FIELDS}
        if existing != event["before"]:
            raise SystemExit("卡片已有其他评分，不能覆盖；请保留批次并核对冲突")
        for field in SCHEDULING_FIELDS:
            current[field] = deepcopy(event["after"][field])
    if cards != before:
        save_cards(cards_path, cards)
    return cards


def display_card(card, number, total):
    return {"id": card["id"], "knowledge_id": card["knowledge_id"],
            "title": card["title"], "content": card.get("content") or card["prepared_explanation"],
            "presentation": "knowledge_statement",
            "source": card["source"], "number": number, "total": total,
            "feedback": RATING_LABELS}


def batch_result(batch):
    position, total = len(batch["events"]), len(batch["cards"])
    return {"batch_id": batch["id"], "completed": position, "total": total,
            "done": position == total,
            "next": display_card(batch["cards"][position], position + 1, total) if position < total else None}


def cmd_prepare(args):
    # 不覆盖尚未完成的整组；恢复与展示直接读已经准备好的内容。
    if os.path.exists(args.batch):
        old = load_batch(args.batch, args.file)
        sync_batch(args.file, old)
        if len(old["events"]) < len(old["cards"]):
            raise SystemExit("已有未完成回忆批次，请运行 batch-next 继续；不要逐卡重新生成")
        archive = Path(args.batch).parent / "batches" / (old["id"] + ".json")
        if archive.exists():
            if json.loads(archive.read_text(encoding="utf-8")) != old:
                raise SystemExit("批次归档冲突，保留原文件")
        else:
            save_batch(archive, old)
    with open(args.input, encoding="utf-8") as stream:
        entries = json.load(stream)
    if not isinstance(entries, list) or not 1 <= len(entries) <= 10:
        raise SystemExit("每次须预备好整组 1 至 10 张具体知识卡，默认建议 5 张")
    existing = load_cards_for_update(args.file)
    existing_by_knowledge = {c.get("knowledge_id"): c for c in existing if c.get("knowledge_id")}
    prepared, knowledge_ids, targets = [], set(), set()
    today = parse_date(args.date) if args.date else date.today()
    for item in entries:
        if not isinstance(item, dict):
            raise SystemExit("预备卡片必须为对象")
        required = ("knowledge_id", "title", "source")
        if any(not isinstance(item.get(k), str) or not item[k].strip() for k in required):
            raise SystemExit("每张卡必须预存知识点编号、具体标题、知识正文和来源")
        content = item.get("content") or item.get("prepared_explanation")
        if not isinstance(content, str) or not content.strip():
            raise SystemExit("每张卡必须有陈述式知识正文，不能只有标题或提问")
        if re.search(r"[？?]\s*$|^(?:请(?:回忆|回答|说明|思考)|只回忆|回忆[:：]|想一想|思考[:：]|为什么|如何|是否|何时)", content.strip()):
            raise SystemExit("知识卡必须直接陈述知识内容，不能要求用户回忆问题或回答问题")
        if item["title"].strip().casefold() in {"操作系统", "线程", "同步", "java", "java基础", "计算机网络", "数据库", "基础知识", "复习知识点"}:
            raise SystemExit("泛主题不能直接当卡片；请缩小到具体机制、结论或适用边界")
        if item.get("id") is not None and (not isinstance(item["id"], str) or not item["id"].strip()):
            raise SystemExit("卡片编号必须是非空字符串")
        if not isinstance(item.get("cue", ""), str):
            raise SystemExit("回忆线索必须是字符串")
        if not isinstance(item.get("tags", []), list) or any(not isinstance(t, str) for t in item.get("tags", [])):
            raise SystemExit("标签必须是字符串数组")
        if any(re.search(r"TODO|待补充|稍后生成|临时生成|待准备", text, re.I) for text in [*(item[k] for k in required), content]):
            raise SystemExit("回忆卡不能含待生成占位内容")
        target = re.sub(r"\s+", "", item["title"] + content).casefold()
        if item["knowledge_id"] in knowledge_ids or target in targets:
            raise SystemExit("整组卡片须对应不同的具体知识点，不能重复凑数")
        knowledge_ids.add(item["knowledge_id"])
        targets.add(target)
        known = existing_by_knowledge.get(item["knowledge_id"])
        if known and item.get("id") and item["id"] != known["id"]:
            raise SystemExit("此知识点已有卡片，请沿用原编号与历史")
        current = find_card(existing, item["id"]) if item.get("id") else known
        if current is None:
            cid = item.get("id") or next_auto_id(existing + prepared)
            if find_card(existing + prepared, cid):
                raise SystemExit("卡片编号重复")
            current = {"id": cid, "created": today.isoformat(), "state": "new",
                       "stability": None, "difficulty": None, "due": today.isoformat(),
                       "last_review": None, "reps": 0, "lapses": 0, "history": [],
                       "tags": item.get("tags", []), "application_note": ""}
        elif current.get("knowledge_id") and current["knowledge_id"] != item["knowledge_id"]:
            raise SystemExit("不能把旧卡改绑到另一知识点")
        current = deepcopy(current)
        current.update({k: item[k].strip() for k in required})
        current.update(kind="knowledge", content=content.strip(),
                       focus=item.get("focus", ""),
                       prepared_explanation=item.get("prepared_explanation") or content.strip(),
                       cue=item.get("cue", ""))
        if any(p["id"] == current["id"] for p in prepared):
            raise SystemExit("同一卡片不能在本组重复出现")
        prepared.append(current)
    batch = {"version": 1, "id": datetime.now(timezone.utc).strftime("B-%Y%m%dT%H%M%S-") + uuid4().hex[:8],
             "cards_path": os.path.relpath(os.path.abspath(args.file), os.path.dirname(os.path.abspath(args.batch))), "date": today.isoformat(),
             "cards": prepared, "events": []}
    save_batch(args.batch, batch)
    sync_batch(args.file, batch)
    result = batch_result(batch)
    # 第一张展示前将整组可见内容交给呈现层，反馈后无需再构思或读取材料。
    result["prepared_cards"] = [display_card(c, i + 1, len(prepared)) for i, c in enumerate(prepared)]
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_batch_next(args):
    batch = load_batch(args.batch, args.file)
    sync_batch(args.file, batch)
    print(json.dumps(batch_result(batch), ensure_ascii=False, indent=2))


def retention_path(cards_path):
    return Path(str(cards_path) + ".settings.json")


def validate_retention(percent):
    if type(percent) is not int or percent not in RETENTION_PRESETS:
        raise ValueError("目标记忆保留率请选择 90% 或 95%")
    return percent


def read_retention(cards_path):
    try:
        data = json.loads(retention_path(cards_path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return 90
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("复习设置文件格式有误，请检查卡库旁的设置文件")
    return validate_retention(data.get("retention_percent"))


def write_retention(cards_path, percent):
    save_batch(retention_path(cards_path), {
        "version": 1, "retention_percent": validate_retention(percent),
    })


def cmd_retention(args):
    if args.percent is not None:
        write_retention(args.file, args.percent)
    print(f"目标记忆保留率：{read_retention(args.file)}%")


def cmd_batch_rate(args):
    batch = load_batch(args.batch, args.file)
    cards = sync_batch(args.file, batch)
    previous = next((e for e in batch["events"] if e["card_id"] == args.card_id), None)
    if previous:
        if previous["rating"] != args.rating:
            raise SystemExit("此卡已保存不同反馈；不能把重试当作修改，需明确发起更正")
        result = batch_result(batch)
        result.update(already_recorded=True, rated_card=args.card_id, due=previous["after"]["due"])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if len(batch["events"]) == len(batch["cards"]):
        raise SystemExit("本组已完成，不自动生成新卡")
    expected = batch["cards"][len(batch["events"])]
    if args.card_id != expected["id"]:
        raise SystemExit("反馈与当前卡片编号不匹配，避免误记到下一张")
    current = find_card(cards, args.card_id)
    before = {field: deepcopy(current.get(field)) for field in SCHEDULING_FIELDS}
    after = deepcopy(current)
    today = parse_date(args.date) if args.date else date.today()
    if after.get("last_review") and today < parse_date(after["last_review"]):
        raise SystemExit("评分日期早于已有复习，停止写入")
    schedule(after, args.rating, today, read_retention(args.file) / 100)
    token = batch["id"] + ":" + args.card_id
    after["history"][-1]["batch_event_id"] = token
    batch["events"].append({"event_id": token, "card_id": args.card_id, "rating": args.rating,
                             "before": before, "after": {field: after[field] for field in SCHEDULING_FIELDS}})
    save_batch(args.batch, batch)
    sync_batch(args.file, batch)
    result = batch_result(batch)
    result.update(already_recorded=False, rated_card=args.card_id, due=after["due"])
    print(json.dumps(result, ensure_ascii=False, indent=2))


# ---- 子命令 ----

def cmd_add(args):
    cards = load_cards_for_update(args.file)
    card_id = args.id or next_auto_id(cards)
    if find_card(cards, card_id):
        raise SystemExit("卡片 id 已存在：%s" % card_id)
    today = parse_date(args.date) if args.date else date.today()
    title = args.title or args.front
    if not title or not title.strip():
        raise SystemExit("知识卡必须提供非空 --title；不需要标准答案")
    knowledge_id = args.knowledge_id or ("K-" + (card_id[2:] if card_id.startswith("C-") else card_id))
    card = {
        "id": card_id,
        "kind": "knowledge",
        "knowledge_id": knowledge_id,
        "title": title,
        "cue": args.cue or "",
        "tags": parse_tags(args.tags),
        "source": args.source or "",
        "created": today.isoformat(),
        "state": "new",
        "stability": None,
        "difficulty": None,
        "due": today.isoformat(),
        "last_review": None,
        "reps": 0,
        "lapses": 0,
        "history": [],
        "application_note": "",
    }
    # 保留旧 CLI 调用的兼容性；新流程不创建问答背面，不删除旧卡及历史。
    if args.front is not None:
        card["front"] = args.front
    if args.back is not None:
        card["back"] = args.back
    cards.append(card)
    save_cards(args.file, cards)
    print("[%s] 已建卡 | 标签: %s | 来源: %s | 到期: %s"
          % (card_id, ",".join(card["tags"]) or "-", card["source"] or "-", card["due"]))


def cmd_show(args):
    cards, bad = load_cards(args.file)
    today = parse_date(args.date) if args.date else date.today()
    due, fresh = [], []
    for card in cards:
        if card.get("state") == "new":
            fresh.append(card)
        else:
            due_raw = card.get("due")
            try:
                is_due = date.fromisoformat(due_raw) <= today
            except (TypeError, ValueError):
                is_due = True  # 无合法到期日的旧卡按到期处理
            if is_due:
                due.append(card)
    due.sort(key=lambda c: c.get("due") or "")
    if not args.all:
        print("到期 %d 张 | 新卡 %d 张 | 共 %d 张（截至 %s）"
              % (len(due), len(fresh), len(cards), today.isoformat()))
        for card in due:
            _print_card(card, today)
        for card in fresh:
            _print_card(card, today)
    else:
        print("共 %d 张（截至 %s）" % (len(cards), today.isoformat()))
        for card in sorted(cards, key=lambda c: c.get("due") or ""):
            _print_card(card, today, force=True)
    if bad:
        print("警告：%d 行损坏已跳过：" % len(bad), file=sys.stderr)
        for lineno, _, _err in bad:
            print("  第 %d 行" % lineno, file=sys.stderr)


def _print_card(card, today, force=False):
    tags = ",".join(card.get("tags") or [])
    head = "[%s]" % card.get("id")
    if card.get("state") == "new":
        status = "new"
    else:
        status = "due %s" % card.get("due")
        last_raw = card.get("last_review")
        if last_raw:
            status += "，上次 %s" % last_raw
    title = card.get("title") or card.get("front", "")
    line = "%s (%s) [%s] %s" % (head, status, tags or "-", title)
    if card.get("cue"):
        line += " | 回忆线索：" + card["cue"]
    if force:
        line += " | S=%s D=%s reps=%s lapses=%s" % (
            card.get("stability"), card.get("difficulty"),
            card.get("reps"), card.get("lapses"))
    print(line)


def cmd_rate(args):
    if args.rating not in RATING_LABELS:
        raise SystemExit("评分必须是 1~4（1=重来 2=困难 3=良好 4=简单）")
    cards = load_cards_for_update(args.file)
    card = find_card(cards, args.card_id)
    if card is None:
        raise SystemExit("找不到卡片 %s；可用 id 见 show --all" % args.card_id)
    today = parse_date(args.date) if args.date else date.today()
    old_s, old_d, r_now, ivl = schedule(card, args.rating, today, read_retention(args.file) / 100)
    save_cards(args.file, cards)
    print("[%s] 评分 %d（%s）" % (card["id"], args.rating, RATING_LABELS[args.rating]))
    print("  稳定度 %s → %s | 难度 %s → %s | 回忆率 %s"
          % (_fmt(old_s), card["stability"], _fmt(old_d), card["difficulty"],
             "%d%%" % round(r_now * 100) if r_now is not None else "-"))
    print("  间隔 %d 天 | 下次到期 %s" % (ivl, card["due"]))


def _fmt(value):
    if value is None:
        return "-"
    return str(value)


def cmd_stats(args):
    cards, bad = load_cards(args.file)
    today = parse_date(args.date) if args.date else date.today()
    days = args.days
    fresh = [c for c in cards if c.get("state") == "new"]
    review = [c for c in cards if c.get("state") == "review"]
    print("总 %d | 新卡 %d | 复习中 %d（截至 %s）"
          % (len(cards), len(fresh), len(review), today.isoformat()))
    if review:
        due_now = [c for c in review if _due_le(c, today)]
        print("今日到期：%d" % len(due_now))
        buckets = {}
        for card in review:
            due_raw = card.get("due")
            try:
                d = date.fromisoformat(due_raw)
            except (TypeError, ValueError):
                continue
            offset = (d - today).days
            if 0 <= offset < days:
                buckets[offset] = buckets.get(offset, 0) + 1
        if buckets:
            print("未来 %d 天到期分布：%s"
                  % (days, " ".join("%+d日:%d" % (k, v)
                                    for k, v in sorted(buckets.items()))))
        hardest = sorted([c for c in review if c.get("difficulty") is not None],
                         key=lambda c: -float(c["difficulty"]))[:5]
        if hardest:
            print("最难 5 张：" + " ".join(
                "%s(D%.1f)" % (c["id"], float(c["difficulty"])) for c in hardest))
        lapsed = sorted([c for c in review if c.get("lapses")],
                        key=lambda c: -int(c.get("lapses") or 0))[:5]
        if lapsed:
            print("遗忘最多：" + " ".join(
                "%s(%s次)" % (c["id"], c.get("lapses")) for c in lapsed))
    if fresh:
        print("待建复习计划的新卡：" + " ".join(c["id"] for c in fresh))
    if bad:
        print("警告：%d 行损坏已跳过：" % len(bad), file=sys.stderr)
        for lineno, _, _err in bad:
            print("  第 %d 行" % lineno, file=sys.stderr)


def _due_le(card, today):
    try:
        return date.fromisoformat(card.get("due")) <= today
    except (TypeError, ValueError):
        return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="FSRS 复习卡片调度器（日粒度）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="新建卡片")
    p_add.add_argument("file")
    p_add.add_argument("--title", help="知识点标题；卡片无需作答或标准答案")
    p_add.add_argument("--cue", default="", help="可选回忆范围或笔记定位")
    p_add.add_argument("--knowledge-id", help="知识点编号 K-xxx，与测试题关联")
    p_add.add_argument("--front", default=None, help=argparse.SUPPRESS)
    p_add.add_argument("--back", default=None, help=argparse.SUPPRESS)
    p_add.add_argument("--tags", default="", help="逗号分隔标签")
    p_add.add_argument("--source", default="", help="出处（Q-xxx/材料页码等）")
    p_add.add_argument("--id", default=None, help="自定义 id（默认自动 C-###）")
    p_add.add_argument("--date", default=None, help="创建日期 YYYY-MM-DD")
    p_add.set_defaults(func=cmd_add)

    p_show = sub.add_parser("show", help="查看到期任务")
    p_show.add_argument("file")
    p_show.add_argument("--date", default=None, help="按此日期计算到期")
    p_show.add_argument("--all", action="store_true", help="列出全部卡片")
    p_show.set_defaults(func=cmd_show)

    p_rate = sub.add_parser("rate", help="记录一次复习")
    p_rate.add_argument("file")
    p_rate.add_argument("card_id")
    p_rate.add_argument("rating", type=int, help="1=重来 2=困难 3=良好 4=简单")
    p_rate.add_argument("--date", default=None, help="复习日期 YYYY-MM-DD")
    p_rate.set_defaults(func=cmd_rate)

    p_stats = sub.add_parser("stats", help="统计与到期分布")
    p_stats.add_argument("file")
    p_stats.add_argument("--date", default=None, help="按此日期统计")
    p_stats.add_argument("--days", type=int, default=7, help="未来 N 天分布（默认 7）")
    p_stats.set_defaults(func=cmd_stats)

    p_prepare = sub.add_parser("prepare", help="整组预存 1 至 10 张具体知识卡后再开始")
    p_prepare.add_argument("file")
    p_prepare.add_argument("--batch", required=True)
    p_prepare.add_argument("--input", required=True, help="完整预备卡片JSON数组")
    p_prepare.add_argument("--date")
    p_prepare.set_defaults(func=cmd_prepare)
    p_next = sub.add_parser("batch-next", help="直接呈现已备好下一张，不生成新卡")
    p_next.add_argument("file")
    p_next.add_argument("--batch", required=True)
    p_next.set_defaults(func=cmd_batch_next)
    p_rate = sub.add_parser("batch-rate", help="一次调用保存反馈并返回已准备的下一张")
    p_rate.add_argument("file")
    p_rate.add_argument("card_id")
    p_rate.add_argument("rating", type=int, choices=range(1, 5))
    p_rate.add_argument("--batch", required=True)
    p_rate.add_argument("--date")
    p_rate.set_defaults(func=cmd_batch_rate)

    p_retention = sub.add_parser("retention", help="查看或设置目标记忆保留率")
    p_retention.add_argument("file")
    p_retention.add_argument("--percent", type=int, choices=RETENTION_PRESETS)
    p_retention.set_defaults(func=cmd_retention)

    args = parser.parse_args(argv)
    try:
        if args.func in (cmd_add, cmd_rate, cmd_prepare, cmd_batch_next, cmd_batch_rate, cmd_retention):
            with cards_lock(args.file):
                args.func(args)
        else:
            args.func(args)
    except ValueError as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
