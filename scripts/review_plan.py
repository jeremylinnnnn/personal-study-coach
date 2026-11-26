#!/usr/bin/env python3
"""Build one deadline-aware review schedule for all subjects in a study workspace."""

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
import re
import sys
import tempfile
import os


@dataclass(frozen=True)
class Task:
    subject: str
    title: str
    minutes: int
    earliest: date
    deadline: date
    priority: int = 2
    split: bool = True


def parse_day(value):
    if not isinstance(value, str):
        raise ValueError("日期应为 YYYY-MM-DD")
    result = date.fromisoformat(value)
    if value != result.isoformat():
        raise ValueError("日期应为 YYYY-MM-DD")
    return result


def minutes(value, name, minimum=0, maximum=1440):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name}须为 {minimum}–{maximum} 的整数")
    return value


def clock(value):
    if value == "24:00":
        return 1440
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("时段须使用 HH:MM，日末可写 24:00")
    hours, mins = map(int, value.split(":"))
    return hours * 60 + mins


def show_clock(value):
    return f"{value // 60:02d}:{value % 60:02d}"


def intervals(items):
    merged = []
    for item in items:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("时段须为 [开始, 结束]")
        first, last = map(clock, item)
        if first >= last:
            raise ValueError("时段结束须晚于开始，跨午夜请拆成两天")
        merged.append((first, last))
    result = []
    for first, last in sorted(merged):
        if result and first <= result[-1][1]:
            result[-1] = (result[-1][0], max(last, result[-1][1]))
        else:
            result.append((first, last))
    return result


def free_slots(config, cutoff):
    if "windows" not in config:
        if config.get("busy"):
            raise ValueError("只有每日净时长时无需另填忙碌时段，或补充可用时段再计算")
        budget = minutes(config.get("minutes"), "当日净时长")
        return [[0, budget]] if budget else [], budget, False
    windows = intervals(config["windows"])
    busy = intervals(config.get("busy", []))
    free = []
    for first, last in windows:
        cursor = max(first, cutoff)
        for a, b in busy:
            if a >= last:
                break
            if b <= cursor:
                continue
            if cursor < a:
                free.append([cursor, a])
            cursor = max(cursor, b)
        if cursor < last:
            free.append([cursor, last])
    available = sum(last - first for first, last in free)
    budget = minutes(config.get("minutes", available), "每日复习上限")
    return free, min(available, budget), True


def card_tasks(workspace, subject_id, subject, title, start, deadline):
    path = workspace / "courses" / subject_id / "cards.jsonl"
    if not path.exists():
        return
    per_card = minutes(subject.get("card_minutes", 2), "单张卡预计分钟", 1, 30)
    seen = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        card = json.loads(line)
        card_id = card["id"]
        if not isinstance(card_id, str) or card_id in seen:
            raise ValueError(f"{path.name} 第 {number} 行卡片编号缺失或重复")
        seen.add(card_id)
        due = parse_day(card["due"])
        if due <= deadline:
            yield Task(title, f"知识卡 {card_id} · {card['title']}", per_card,
                       max(start, due), deadline, priority=1, split=False)


def collect_tasks(config, workspace, start, horizon):
    tasks, exams, seen = [], [], set()
    if not config["subjects"]:
        raise ValueError("请至少记录一个科目")
    for subject in config["subjects"]:
        sid = subject["id"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", sid) or sid in seen:
            raise ValueError("科目 ID 须唯一，使用小写字母、数字、下划线或连字符")
        seen.add(sid)
        title = subject["name"]
        exam = parse_day(subject["exam_date"]) if subject.get("exam_date") else None
        exams.append((title, exam))
        if exam and exam < start:
            continue
        exam_limit = exam - timedelta(days=1) if exam else horizon
        for item in subject.get("tasks", []):
            total = minutes(item["minutes"], "任务估时", 1, 100000)
            done = minutes(item.get("completed_minutes", 0), "已完成分钟", 0, total)
            if done == total:
                continue
            release = max(start, parse_day(item.get("earliest", start.isoformat())))
            deadline = min(exam_limit, parse_day(item.get("deadline", exam_limit.isoformat())))
            split = item.get("split", True)
            if type(split) is not bool:
                raise ValueError("split 应为 true 或 false")
            tasks.append(Task(title, item["title"], total-done, release, deadline,
                              minutes(item.get("priority", 2), "任务优先级", 1, 3), split))
        tasks.extend(card_tasks(workspace, sid, subject, title, start, min(horizon, exam_limit)))
    return tasks, exams


def build(config, workspace, start, not_before=0):
    availability = sorted((parse_day(day), values) for day, values in config["days"].items())
    availability = [(day, values) for day, values in availability if day >= start]
    horizon = availability[-1][0] if availability else start
    tasks, exams = collect_tasks(config, workspace, start, horizon)
    order = sorted(range(len(tasks)), key=lambda i: (tasks[i].deadline, tasks[i].priority, tasks[i].earliest, i))
    remaining = [task.minutes for task in tasks]
    days = []
    for day, values in availability:
        slots, budget, timed = free_slots(values, not_before if day == start else 0)
        plan, left = [], budget
        for slot in slots:
            while slot[0] < slot[1] and left:
                room = min(left, slot[1]-slot[0])
                selected = next((i for i in order if remaining[i]
                                 and tasks[i].earliest <= day <= tasks[i].deadline
                                 and (tasks[i].split or remaining[i] <= room)), None)
                if selected is None:
                    break
                task = tasks[selected]
                length = min(remaining[selected], room)
                end = slot[0] + length
                label = f"{show_clock(slot[0])}–{show_clock(end)}" if timed else f"第 {len(plan)+1} 项"
                plan.append((label, task.subject, task.title, length))
                slot[0] = end
                remaining[selected] -= length
                left -= length
        days.append((day, budget, plan))
    return days, exams, [(tasks[i], remaining[i]) for i in order if remaining[i]]


def table_text(value):
    return str(value).replace("|", r"\|").replace("\n", " ").replace("\r", " ")


def render(config, days, exams, pending):
    lines = ["# 全局复习安排表", ""]
    lines.extend(f"- {table_text(subject)}：{day.isoformat() if day else '考试日期待定'}" for subject, day in exams)
    if config.get("note"):
        lines += ["", str(config["note"])]
    lines += ["", "| 日期 | 时段 / 顺序 | 科目 | 复习任务 | 用时（分钟） |", "| --- | --- | --- | --- | ---: |"]
    for day, budget, plan in days:
        for label, subject, title, length in plan:
            lines.append(f"| {day} | {label} | {table_text(subject)} | {table_text(title)} | {length} |")
        used = sum(item[3] for item in plan)
        lines.append(f"| {day} | 当日合计 |  | 可用 {budget} · 余量 {budget-used} | {used} |")
    if not days:
        lines += ["", "当前还没有可安排的日期。"]
    if pending:
        lines += ["", "## 尚未排入的任务", ""]
        for task, left in pending:
            timing = f"最晚 {task.deadline}" if task.earliest <= task.deadline else "开始日期晚于截止日期"
            needs = "，需要连续时段" if not task.split else ""
            lines.append(f"- {table_text(task.subject)} · {table_text(task.title)}，剩余 {left} 分钟，{timing}{needs}。")
    return "\n".join(lines) + "\n"


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("config", type=Path, help="review-plan.json，与各科目录位于同一工作区")
    cli.add_argument("--from", dest="start", help="从此日期起重排")
    cli.add_argument("--not-before", help="首日实际最早开始时刻，适用于具体时段模式")
    cli.add_argument("--output", type=Path, help="Markdown 总表路径，省略则输出到标准输出")
    args = cli.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        start = parse_day(args.start or config["start"])
        cutoff = clock(args.not_before) if args.not_before else 0
        result = render(config, *build(config, args.config.parent, start, cutoff))
        if not args.output:
            print(result, end="")
            return
        if args.output.resolve() == args.config.resolve():
            raise ValueError("总表须与输入配置使用不同文件")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output.parent, delete=False) as file:
            temp_path = Path(file.name)
        try:
            temp_path.write_text(result, encoding="utf-8")
            os.replace(temp_path, args.output)
        finally:
            temp_path.unlink(missing_ok=True)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"无法生成复习表：{error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
