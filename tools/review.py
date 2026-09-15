# -*- coding: utf-8 -*-
"""
艾宾浩斯记忆曲线复习提醒
========================
按记忆曲线算出「今天该复习哪些内容」，并把要复习的内容直接打印出来。

复习时间的两种来源
------------------
1. 文件内日期标记（推荐，用于 Grammar / Sentence）
   在笔记里另起一行写日期，作为这一段内容的「学习时间」：

       2026年9月15日18:02:27
       这里写这次学到的内容……
       可以写很多行

       2026年9月16日09:10:00
       又一段新内容……

   脚本会把「日期标记」到「下一个日期标记」之间的内容视为一个内容块，
   单独计算复习时间。所以你给新增内容标上日期，它就会自动进入复习计划。
   支持格式：2026年9月15日18:02:27 / 2026年9月15日 / 2026-09-15

2. git 提交时间（用于没有日期标记的文件，如 Word/、2026_daily_record/）
   每个文件每次提交视为一次学习，按提交日期排复习。

用法（在仓库根目录执行）：
    python tools/review.py                    # 查看今天要复习的内容
    python tools/review.py --done             # 复习完成后标记今天全部完成
    python tools/review.py --done 1,3         # 只标记第 1、3 项
    python tools/review.py --upcoming 14      # 查看未来 14 天的复习安排
    python tools/review.py --status           # 查看每个文件 / 内容块的下次复习时间
    python tools/review.py --markers          # 列出识别到的所有日期标记（检查格式用）
    python tools/review.py --stamp            # 打印当前时间的标记文本，方便粘贴进笔记
    python tools/review.py --full             # 显示完整内容，不截断
    python tools/review.py --reset            # 清空复习记录，重新开始
    python tools/review.py --date 2026-09-20  # 假装今天是某一天（测试用）

原理：
    1. 有日期标记的文件：按标记把文件切成内容块，每块按标记日期 + 艾宾浩斯曲线排复习；
    2. 没有日期标记的文件：用 `git log --name-status` 的提交日期排复习；
    3. 复习过的记录在 .review_state.json，不会重复提醒。

注意：改了文件记得 commit（或至少写上日期标记），脚本才知道有新东西要复习。
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# ==================== 配置区（可按需修改）====================

# 艾宾浩斯复习间隔（天）。想更密集就改成 [1, 2, 3, 5, 8, 13] 之类的
INTERVALS = [1, 2, 4, 7, 15, 30, 60, 120]

# 用「文件内日期标记」来切分内容块的目录（其它目录按 git 提交时间）
DATE_MARKER_DIRS = ("Grammar", "Sentence")

# 日期标记的格式：行首（可带 markdown 符号）出现的 年-月-日[ 时:分:秒]
DATE_MARKER_RE = re.compile(
    r"^\s*[#>*+\-\s\[]*"                       # 允许行首的 #、-、>、[ 等符号
    r"(?P<year>\d{4})\s*(?:年|[-/.])\s*"
    r"(?P<month>\d{1,2})\s*(?:月|[-/.])\s*"
    r"(?P<day>\d{1,2})\s*日?\s*"
    r"(?:"
    r"(?P<hour>\d{1,2})\s*[:：时]\s*(?P<minute>\d{1,2})"
    r"(?:\s*[:：分]\s*(?P<second>\d{1,2}))?\s*秒?"
    r")?"
)

# 每项变更内容默认最多显示多少行
PREVIEW_LINES = 25

# --upcoming 默认预览多少天
DEFAULT_UPCOMING = 7

# 复习记录文件名（存放在仓库根目录，已加入 .gitignore）
STATE_FILE = ".review_state.json"

# 不纳入复习计划的目录 / 文件 / 后缀
IGNORE_DIRS = {".git", ".vscode", ".github", ".idea", "__pycache__", "tools", "scripts"}
IGNORE_FILES = {".gitignore", "README.md", STATE_FILE}
IGNORE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".svg",
    ".pdf", ".zip", ".7z", ".rar", ".exe", ".dll", ".mp3", ".mp4",
    ".py", ".bat", ".cmd", ".ps1", ".sh", ".json", ".lock", ".yml", ".yaml",
}

# ==================== 基础工具 ====================

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
BAR = "═" * 62
SUB = "─" * 62


def setup_stdout() -> None:
    """尽量让 Windows 终端能正确显示中文。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


def find_repo_root() -> Path:
    """定位仓库根目录。"""
    here = Path(__file__).resolve().parent
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(here),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip())
    except OSError:
        pass
    return here.parent if here.name in ("tools", "scripts") else here


REPO = find_repo_root()


def git(*args: str) -> Optional[str]:
    """执行 git 命令，失败返回 None。core.quotepath=false 用于正常显示中文文件名。"""
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def is_ignored_path(rel_posix: str) -> bool:
    """判断某个仓库相对路径是否应被忽略。"""
    path = Path(rel_posix)
    if any(part in IGNORE_DIRS for part in path.parts[:-1]):
        return True
    if path.name in IGNORE_FILES:
        return True
    if path.suffix.lower() in IGNORE_SUFFIXES:
        return True
    return False


# ==================== 解析「文件内的日期标记」 ====================


class Block(object):
    """文件里的一段内容：从某个日期标记开始，到下一个日期标记之前。"""

    __slots__ = ("path", "start", "end", "learned", "stamp", "marker_text", "lines")

    def __init__(
        self,
        path: str,
        start: int,
        end: int,
        learned: date,
        stamp: str,
        marker_text: str,
        lines: List[str],
    ) -> None:
        self.path = path
        self.start = start          # 起始行号（1-based，含）
        self.end = end              # 结束行号（1-based，含）
        self.learned = learned      # 学习日期
        self.stamp = stamp          # 归一化时间戳，如 2026-09-15 18:02:27
        self.marker_text = marker_text  # 原始标记文本
        self.lines = lines          # 该块的内容行

    @property
    def key(self) -> str:
        return "%s@block:%s" % (self.path, self.stamp)


def parse_date_marker(line: str) -> Optional[Tuple[date, str, str]]:
    """识别日期标记行，返回 (日期, 归一化时间戳, 原始文本)；不是标记则返回 None。"""
    m = DATE_MARKER_RE.match(line.rstrip())
    if not m:
        return None
    try:
        day = date(int(m.group("year")), int(m.group("month")), int(m.group("day")))
    except ValueError:
        return None
    hour, minute, second = m.group("hour"), m.group("minute"), m.group("second")
    if hour is not None:
        stamp = "%s %02d:%02d" % (day.isoformat(), int(hour), int(minute or 0))
        if second is not None:
            stamp += ":%02d" % int(second)
    else:
        stamp = day.isoformat()
    return day, stamp, m.group(0).strip()


def parse_blocks(path: str, text: str) -> List[Block]:
    """
    把文件按日期标记切成若干内容块。
    - 标记之前的开头内容（如果有）算作第 0 块，学习日期用 git 首次提交日期兜底。
    - 没有日期标记时返回空列表。
    """
    lines = text.splitlines()
    found: List[Tuple[int, date, str, str]] = []  # (行号, 日期, 时间戳, 原始文本)
    seen: Dict[str, int] = {}
    for i, line in enumerate(lines):
        parsed = parse_date_marker(line)
        if not parsed:
            continue
        day, stamp, raw = parsed
        # 同一时间戳出现多次时加序号，保证记录 key 唯一
        seen[stamp] = seen.get(stamp, 0) + 1
        if seen[stamp] > 1:
            stamp = "%s~%d" % (stamp, seen[stamp])
        found.append((i, day, stamp, raw))

    if not found:
        return []

    blocks: List[Block] = []

    # 开头的无标记内容
    head_end = found[0][0]
    head = [ln for ln in lines[:head_end] if ln.strip()]
    if head:
        fallback = file_first_commit_date(path)
        blocks.append(
            Block(
                path,
                1,
                head_end,
                fallback,
                "%s|head" % fallback.isoformat(),
                "（文件开头，无日期标记）",
                lines[:head_end],
            )
        )

    for idx, (line_no, day, stamp, raw) in enumerate(found):
        next_start = found[idx + 1][0] if idx + 1 < len(found) else len(lines)
        blocks.append(
            Block(
                path,
                line_no + 1,
                next_start,
                day,
                stamp,
                raw,
                lines[line_no + 1 : next_start],
            )
        )
    return blocks


def collect_blocks() -> Dict[str, List[Block]]:
    """扫描 DATE_MARKER_DIRS 下所有文件的日期标记。"""
    result: Dict[str, List[Block]] = {}
    for rel in iter_worktree_files():
        top = Path(rel).parts[0]
        if top not in DATE_MARKER_DIRS:
            continue
        try:
            text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "年" not in text and not DATE_MARKER_RE.search(text):
            continue
        blocks = parse_blocks(rel, text)
        if blocks:
            result[rel] = blocks
    return result


_FIRST_COMMIT_CACHE: Dict[str, Optional[date]] = {}


def file_first_commit_date(path: str) -> date:
    """文件首次被提交的日期；取不到就用文件修改时间兜底。"""
    cached = _FIRST_COMMIT_CACHE.get(path)
    if cached is not None:
        return cached
    result: Optional[date] = None
    out = git("log", "--diff-filter=A", "--date=short", "--format=%ad", "--", path)
    if out and out.strip():
        dates = [ln.strip() for ln in out.splitlines() if ln.strip()]
        if dates:
            try:
                result = date.fromisoformat(dates[-1])  # git log 新→旧，最后一行最早
            except ValueError:
                result = None
    if result is None:
        try:
            result = datetime.fromtimestamp((REPO / path).stat().st_mtime).date()
        except OSError:
            result = date.today()
    _FIRST_COMMIT_CACHE[path] = result
    return result


# ==================== 采集「学习事件」（按 git 提交日期） ====================


def collect_events() -> Dict[str, Dict[str, List[str]]]:
    """
    返回 {文件路径: {日期: [commit 短哈希, ...]}}。
    日期即「学习日期」，来自 git 提交历史。
    """
    events: Dict[str, Dict[str, List[str]]] = {}

    out = git("log", "--date=short", "--name-status", "--pretty=format:@@@%H|%ad")
    if out:
        current: Optional[Tuple[str, str]] = None
        for raw in out.splitlines():
            line = raw.rstrip("\r")
            if line.startswith("@@@"):
                commit, _, day = line[3:].partition("|")
                current = (commit.strip(), day.strip())
                continue
            if not line.strip() or current is None:
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            status, path = parts[0], parts[-1]  # 重命名时取新路径
            if status.startswith("D"):  # 已删除的文件不提醒
                continue
            if is_ignored_path(path):
                continue
            events.setdefault(path, {}).setdefault(current[1], []).append(current[0][:8])

    # 从未提交过、但工作区里存在的文件：用文件修改时间兜底，保证不漏
    for rel in iter_worktree_files():
        if rel in events:
            continue
        full = REPO / rel
        try:
            mtime = datetime.fromtimestamp(full.stat().st_mtime).date().isoformat()
        except OSError:
            continue
        events.setdefault(rel, {}).setdefault(mtime, [])

    # 只保留当前工作区里仍然存在的文件（被删除 / 被重命名掉的旧路径不再提醒）
    return {path: dates for path, dates in events.items() if (REPO / path).is_file()}


def iter_worktree_files() -> List[str]:
    """列出工作区中需要纳入计划的所有文件（相对路径）。"""
    result: List[str] = []
    for path in sorted(REPO.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(REPO).as_posix()
        except ValueError:
            continue
        if is_ignored_path(rel):
            continue
        result.append(rel)
    return result


def uncommitted_files() -> List[str]:
    """列出有未提交改动 / 新增的文件，用于提示用户先把它们 commit 进来。"""
    out = git("status", "--porcelain", "-uall")
    result: List[str] = []
    for line in (out or "").splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:].strip()
        if "D" in status:  # 已删除的文件不用管
            continue
        if " -> " in path:
            path = path.split(" -> ")[-1]
        path = path.strip('"').strip()
        if not path or path.endswith("/") or is_ignored_path(path):
            continue
        result.append(path)
    return result


# ==================== 复习状态（本地记录） ====================


def state_path() -> Path:
    return REPO / STATE_FILE


def load_state() -> Dict[str, object]:
    path = state_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("reviewed", {})
                return data
        except (json.JSONDecodeError, OSError):
            print("⚠️  复习记录文件损坏，已忽略并重建。")
    return {"reviewed": {}}


def save_state(state: Dict[str, object]) -> None:
    state_path().write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def item_key(path: str, day_str: str, interval: int) -> str:
    return "%s@%s#%d" % (path, day_str, interval)


# ==================== 生成复习计划 ====================


class ReviewItem(object):
    __slots__ = (
        "path", "learned", "interval", "due", "key", "kind",
        "block", "commits", "index", "content",
    )

    def __init__(
        self,
        path: str,
        learned: date,
        interval: int,
        key: str,
        kind: str,
        block: Optional[Block] = None,
        commits: Optional[List[str]] = None,
    ) -> None:
        self.path = path
        self.learned = learned
        self.interval = interval
        self.due = learned + timedelta(days=interval)
        self.key = key
        self.kind = kind                # "block"（文件内日期标记）或 "file"（git 提交）
        self.block = block
        self.commits = commits or []
        self.index = 0
        self.content: Optional[List[str]] = None

    @property
    def round_no(self) -> int:
        return INTERVALS.index(self.interval) + 1

    @property
    def location(self) -> str:
        if self.block is None:
            return "整篇内容（按 git 提交时间）"
        if self.block.start == self.block.end:
            return "第 %d 行（标记行 %s）" % (self.block.start, self.block.marker_text)
        return "第 %d-%d 行（标记 %s）" % (
            self.block.start,
            self.block.end,
            self.block.marker_text,
        )


def build_all_items(
    events: Dict[str, Dict[str, List[str]]],
    blocks: Dict[str, List[Block]],
    reviewed: Dict[str, str],
    with_content: bool = False,
) -> List[ReviewItem]:
    """所有尚未复习的复习项（含未到期），按到期时间升序。
    with_content=True 时会顺便取出内容，并丢弃没有任何内容的项（空文件等）。
    """
    items: List[ReviewItem] = []
    block_paths = set(blocks)

    # 1) 有日期标记的文件：按内容块排（整篇的 git 事件不再参与，避免重复）
    for path, blist in blocks.items():
        for block in blist:
            for interval in INTERVALS:
                key = "%s#%d" % (block.key, interval)
                if key in reviewed:
                    continue
                items.append(
                    ReviewItem(path, block.learned, interval, key, "block", block=block)
                )

    # 2) 没有日期标记的文件：按 git 提交日期排
    for path, dates in events.items():
        if path in block_paths:
            continue
        for day_str, commits in dates.items():
            try:
                learned = date.fromisoformat(day_str)
            except ValueError:
                continue
            for interval in INTERVALS:
                key = item_key(path, day_str, interval)
                if key in reviewed:
                    continue
                items.append(
                    ReviewItem(path, learned, interval, key, "file", commits=commits)
                )

    items.sort(key=lambda it: (it.due, it.path, it.learned, it.interval))

    if with_content:
        kept: List[ReviewItem] = []
        for item in items:
            item.content = item_lines(item)
            if item.content:
                kept.append(item)
        items = kept
    return items


def due_items(items: Sequence[ReviewItem], today: date) -> List[ReviewItem]:
    return [it for it in items if it.due <= today]


def upcoming_map(items: Sequence[ReviewItem], today: date, days: int) -> List[Tuple[date, List[str]]]:
    """未来 days 天内每天有哪些内容要复习。"""
    buckets: Dict[date, List[str]] = {}
    limit = today + timedelta(days=days)
    for item in items:
        if not (today < item.due <= limit):
            continue
        buckets.setdefault(item.due, []).append(item.path)
    return [(d, paths) for d, paths in sorted(buckets.items())]


# ==================== 提取「要复习的内容」 ====================


def added_lines(commit: str, path: str) -> List[str]:
    """取出某次提交中该文件新增/修改的行。"""
    out = git("show", "--format=", "--unified=0", "--no-color", commit, "--", path)
    if not out:
        return []
    lines: List[str] = []
    for raw in out.splitlines():
        if raw.startswith("+++") or raw.startswith("---"):
            continue
        if raw.startswith("+"):
            lines.append(raw[1:])
    return lines


def read_file_lines(path: str) -> List[str]:
    try:
        return (REPO / path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def item_lines(item: ReviewItem) -> List[str]:
    """该复习项对应的内容行（已去掉空行）。"""
    if item.content is not None:
        return item.content

    if item.block is not None:
        return [ln for ln in item.block.lines if ln.strip()]

    collected: List[str] = []
    if item.commits:
        seen = set()
        for commit in item.commits:
            for line in added_lines(commit, item.path):
                if line in seen:
                    continue
                seen.add(line)
                collected.append(line)
    else:
        collected = read_file_lines(item.path)
    return [ln for ln in collected if ln.strip()]


# ==================== 输出 ====================


def fmt_date(d: date) -> str:
    return "%s %s" % (d.isoformat(), WEEKDAYS[d.weekday()])


def print_item(item: ReviewItem, lines: Sequence[str], full: bool) -> None:
    overdue = item.due < TODAY
    flag = "⏰ 逾期 %d 天" % (TODAY - item.due).days if overdue else "🔥 今日到期"
    print(" [%d] %s" % (item.index, item.path))
    print("     %s │ 位置：%s" % (flag, item.location))
    print(
        "     学习日期 %s │ 第 %d 次复习（学习后 %d 天）"
        % (item.learned.isoformat(), item.round_no, item.interval)
    )
    if item.commits:
        print("     来源提交：%s" % ", ".join(item.commits))

    if not lines:
        print("     （这里没有可显示的内容，可能是只删不改，快速回忆即可）")
        print()
        return

    shown = lines if full else lines[:PREVIEW_LINES]
    print(
        "     ── 要复习的内容（共 %d 行%s）──"
        % (len(lines), "" if full else "，展示前 %d 行" % len(shown))
    )
    for ln in shown:
        print("       │ " + ln)
    if not full and len(lines) > len(shown):
        print("       │ ...（还有 %d 行，加 --full 查看全部）" % (len(lines) - len(shown)))
    print()


def print_hint_uncommitted() -> None:
    pending = uncommitted_files()
    if not pending:
        return
    print(SUB)
    print(" ✍️  以下文件有未提交的改动，写上日期标记或 commit 后才会纳入复习计划：")
    for path in pending:
        print("     · %s" % path)
    print()


def command_report(args: argparse.Namespace, state: Dict[str, object]) -> int:
    reviewed: Dict[str, str] = state.get("reviewed", {})  # type: ignore[assignment]
    blocks = collect_blocks()
    events = collect_events()
    all_items = build_all_items(events, blocks, reviewed, with_content=True)
    items = due_items(all_items, TODAY)

    print(BAR)
    print("   📚 艾宾浩斯复习提醒   【%s】" % fmt_date(TODAY))
    print("   仓库：%s" % REPO)
    print(BAR)

    if not items:
        print()
        print("   ✅ 今天没有到期的复习任务，可以自由学习新内容啦～")
        print()

    for i, item in enumerate(items, start=1):
        item.index = i
        print(SUB)
        print_item(item, item_lines(item), full=args.full)

    upcoming = upcoming_map(all_items, TODAY, args.upcoming)
    if upcoming:
        print(SUB)
        print(" 📅 未来 %d 天预告（只统计数量）" % args.upcoming)
        for d, paths in upcoming:
            print("     %s   %d 项" % (fmt_date(d), len(paths)))
        print()

    print_hint_uncommitted()

    print(SUB)
    if items:
        block_count = sum(1 for it in items if it.kind == "block")
        print(
            " 本次共 %d 项待复习（内容块 %d 项 / 整篇文件 %d 项）。"
            % (len(items), block_count, len(items) - block_count)
        )
        print(" 复习完成后执行：python tools/review.py --done")
    print(" 提示：--done 标记完成 / --markers 检查日期标记 / --stamp 生成时间戳")
    print(BAR)
    return 0


def command_done(args: argparse.Namespace, state: Dict[str, object]) -> int:
    reviewed: Dict[str, str] = state.get("reviewed", {})  # type: ignore[assignment]
    blocks = collect_blocks()
    events = collect_events()
    items = due_items(build_all_items(events, blocks, reviewed, with_content=True), TODAY)

    if not items:
        print("✅ 今天没有待复习的项目，无需标记。")
        return 0

    for i, item in enumerate(items, start=1):
        item.index = i

    if args.done == "all":
        targets = items
    else:
        wanted = set()
        for chunk in str(args.done).split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                wanted.add(int(chunk))
        targets = [it for it in items if it.index in wanted]
        if not targets:
            print("⚠️  没有匹配的项目，可用序号：1 ~ %d" % len(items))
            return 1

    for item in targets:
        reviewed[item.key] = TODAY.isoformat()
    state["reviewed"] = reviewed
    save_state(state)

    print("✅ 已标记 %d 项为「今天复习完成」：" % len(targets))
    for item in targets:
        print("   · %s（%s，第 %d 次复习）" % (item.path, item.location, item.round_no))
    print("\n记录已保存到 %s" % state_path())
    return 0


def command_status(args: argparse.Namespace, state: Dict[str, object]) -> int:
    reviewed: Dict[str, str] = state.get("reviewed", {})  # type: ignore[assignment]
    blocks = collect_blocks()
    events = collect_events()
    items = build_all_items(events, blocks, reviewed)

    next_due: Dict[str, date] = {}
    pending_count: Dict[str, int] = {}
    for item in items:
        if item.path not in next_due or item.due < next_due[item.path]:
            next_due[item.path] = item.due
        pending_count[item.path] = pending_count.get(item.path, 0) + 1

    print(BAR)
    print("   📊 各文件复习安排   【%s】" % fmt_date(TODAY))
    print(BAR)

    today_count = 0
    for path in sorted(set(blocks) | set(events)):
        if path in blocks:
            unit = "%d 个日期块" % len(blocks[path])
        else:
            unit = "按 git 提交（%d 次）" % len(events[path])
        if path in next_due:
            due = next_due[path]
            if due <= TODAY:
                today_count += 1
                status = "🔔 今天该复习"
            else:
                status = "下次复习 %s（还有 %d 天）" % (due.isoformat(), (due - TODAY).days)
        else:
            status = "✅ 全部复习完毕"
        print(" · %-38s %-18s %s" % (path, unit, status))

    print()
    print(" 今天有 %d 个文件需要复习。" % today_count)
    print(BAR)
    return 0


def command_markers(args: argparse.Namespace, state: Dict[str, object]) -> int:
    """列出识别到的日期标记，用来确认格式写对了。"""
    blocks = collect_blocks()

    print(BAR)
    print("   🔖 识别到的日期标记   【%s】" % fmt_date(TODAY))
    print(BAR)

    if not blocks:
        print(" 未在 %s 目录下找到日期标记。" % "、".join(DATE_MARKER_DIRS))
        print(" 请另起一行按 2026年9月15日18:02:27 的格式书写。")
        print(BAR)
        return 0

    for path in sorted(blocks):
        print()
        print(" 📄 %s" % path)
        for block in blocks[path]:
            body = len([ln for ln in block.lines if ln.strip()])
            last_due = block.learned + timedelta(days=INTERVALS[-1])
            print(
                "    第 %d-%d 行 │ 标记 %-22s │ 学习 %s │ 内容 %d 行 │ 最后一轮 %s"
                % (
                    block.start,
                    block.end,
                    block.marker_text,
                    block.learned.isoformat(),
                    body,
                    last_due.isoformat(),
                )
            )
    print()
    print(BAR)
    return 0


def command_stamp(args: argparse.Namespace, state: Dict[str, object]) -> int:
    now = datetime.now()
    print("把下面这一行粘贴到笔记里（单独一行）：")
    print()
    print("    %d年%d月%d日%d:%02d:%02d" % (now.year, now.month, now.day, now.hour, now.minute, now.second))
    print()
    return 0


def command_reset(args: argparse.Namespace, state: Dict[str, object]) -> int:
    reviewed: Dict[str, str] = state.get("reviewed", {})  # type: ignore[assignment]
    count = len(reviewed)
    if not count:
        print("复习记录本来就是空的，无需重置。")
        return 0
    if not args.yes:
        answer = input("⚠️  确定要清空全部 %d 条复习记录吗？(y/N) " % count).strip().lower()
        if answer not in ("y", "yes"):
            print("已取消。")
            return 1
    save_state({"reviewed": {}})
    print("🧹 已清空 %d 条复习记录，所有内容将重新进入复习计划。" % count)
    return 0


# ==================== 入口 ====================

TODAY: date = date.today()


def main(argv: Optional[Sequence[str]] = None) -> int:
    global TODAY

    parser = argparse.ArgumentParser(
        description="艾宾浩斯记忆曲线复习提醒（文件内日期标记 + git 提交时间）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--done", nargs="?", const="all", metavar="序号",
                        help="标记今天已复习，可指定序号，如 --done 1,3；不带参数表示全部")
    parser.add_argument("--upcoming", type=int, default=None, metavar="N",
                        help="预告未来 N 天的复习安排（默认 %d 天）" % DEFAULT_UPCOMING)
    parser.add_argument("--status", action="store_true", help="查看每个文件的下一次复习安排")
    parser.add_argument("--markers", action="store_true", help="列出识别到的日期标记（检查格式）")
    parser.add_argument("--stamp", action="store_true", help="生成当前时间戳文本，方便粘贴进笔记")
    parser.add_argument("--reset", action="store_true", help="清空复习记录")
    parser.add_argument("--yes", action="store_true", help="--reset 时跳过确认")
    parser.add_argument("--full", action="store_true", help="显示完整内容，不截断")
    parser.add_argument("--date", metavar="YYYY-MM-DD", help="把「今天」设为指定日期（测试用）")
    args = parser.parse_args(argv)

    if args.date:
        try:
            TODAY = date.fromisoformat(args.date)
        except ValueError:
            print("❌ --date 格式应为 YYYY-MM-DD，例如 2026-09-20")
            return 2

    if args.upcoming is None:
        args.upcoming = DEFAULT_UPCOMING

    if not (REPO / ".git").exists():
        print("⚠️  当前目录不是 git 仓库，没有日期标记的文件将只能按文件修改时间估算。")

    state = load_state()

    if args.stamp:
        return command_stamp(args, state)
    if args.reset:
        return command_reset(args, state)
    if args.done:
        return command_done(args, state)
    if args.status:
        return command_status(args, state)
    if args.markers:
        return command_markers(args, state)
    return command_report(args, state)


if __name__ == "__main__":
    setup_stdout()
    sys.exit(main())
