# -*- coding: utf-8 -*-
"""
艾宾浩斯复习提醒（跑一次 = 当天已学）
=====================================
每天跑一次这个脚本，它就会：
    1. 把「今天该复习的内容」完整打印出来（这就是你今天的复习任务）；
    2. 顺手把今天这些内容记为「今天已复习」，明天不会再重复提醒；
    3. 把「逾期没复习」的内容整理成一张表格（同时写入 复习逾期清单.md）。

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
   单独计算复习时间。支持格式：2026年9月15日18:02:27 / 2026年9月15日 / 2026-09-15

2. git 提交时间（用于没有日期标记的文件，如 Word/、2026_daily_record/）
   每个文件每次提交视为一次学习，按提交日期排复习。

复习间隔怎么算（晚一天复习也不会堆积）
--------------------------------------
第 1 轮：学习日 + 1 天
第 2 轮：第 1 轮实际复习日 + 1 天
第 3 轮：第 2 轮实际复习日 + 2 天
第 4 轮：第 3 轮实际复习日 + 3 天 …… 依此类推（间隔 = INTERVALS 相邻两项之差）

也就是说：按时复习时，复习日正好是学习日 +1、+2、+4、+7、+15、+30、+60、+120 天；
偶尔漏了一天，后面的安排会自动顺延，不会一次冒出好几轮。

用法（在仓库根目录执行）：
    python tools/review.py                    # 今天的复习内容（并记为已复习）
    python tools/review.py --no-mark          # 只看，不记录
    python tools/review.py --catch-up         # 把逾期清单里的内容全部记为「已补复习」
    python tools/review.py --done 1,3         # 只把今天第 1、3 项记为已复习
    python tools/review.py --upcoming 14      # 未来 14 天还会复习哪些
    python tools/review.py --status           # 每段内容下一轮复习的时间
    python tools/review.py --markers          # 列出识别到的日期标记（检查格式用）
    python tools/review.py --stamp            # 打印当前时间戳，方便粘贴进笔记
    python tools/review.py --full             # 内容完整显示，不截断
    python tools/review.py --reset            # 清空复习记录，重新开始
    python tools/review.py --date 2026-09-20  # 假装今天是某一天（测试用）

复习进度保存在 .review_state.json；逾期清单会写到 复习逾期清单.md。
注意：改了文件记得 commit（或给新内容写上日期标记），脚本才知道有新东西要复习。
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

# 每项内容默认最多显示多少行（详细展示今天的内容时）
PREVIEW_LINES = 40

# --upcoming 默认预览多少天
DEFAULT_UPCOMING = 7

# 复习记录文件名（存放在仓库根目录，已加入 .gitignore）
STATE_FILE = ".review_state.json"

# 逾期清单文件名（每次运行都会重新生成，内容为空则删除该文件）
OVERDUE_FILE = "复习逾期清单.md"

# 逾期表格里文件名 / 位置列的宽度
TABLE_PATH_WIDTH = 34
TABLE_LOC_WIDTH = 24

# 不纳入复习计划的目录 / 文件 / 后缀
IGNORE_DIRS = {".git", ".vscode", ".github", ".idea", "__pycache__", "tools", "scripts"}
IGNORE_FILES = {".gitignore", "README.md", STATE_FILE, OVERDUE_FILE}
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


def content_key(path: str, anchor: str, interval: int) -> str:
    """复习记录里的一项：文件 + 内容标识 + 第几轮对应的间隔。"""
    return "%s@%s#%d" % (path, anchor, interval)


# ==================== 复习计划 ====================


class Anchor(object):
    """一段可复习的内容：文件里的一个日期块，或某个文件的一次提交。"""

    __slots__ = ("path", "learned", "anchor", "kind", "block", "commits", "content")

    def __init__(
        self,
        path: str,
        learned: date,
        anchor: str,
        kind: str,
        block: Optional[Block] = None,
        commits: Optional[List[str]] = None,
        content: Optional[List[str]] = None,
    ) -> None:
        self.path = path
        self.learned = learned          # 学习日期
        self.anchor = anchor            # 内容标识（时间戳 / 提交日期 / head）
        self.kind = kind                # "block" 或 "file"
        self.block = block
        self.commits = commits or []
        self.content = content or []    # 这段内容的正文（已去掉空行)

    def key(self, interval: int) -> str:
        return content_key(self.path, self.anchor, interval)

    @property
    def location(self) -> str:
        if self.block is None:
            return "整篇（按 git 提交时间）"
        if self.block.start == self.block.end:
            return "第 %d 行" % self.block.start
        return "第 %d-%d 行" % (self.block.start, self.block.end)


def build_anchors(
    events: Dict[str, Dict[str, List[str]]], blocks: Dict[str, List[Block]]
) -> List[Anchor]:
    """把「日期块」和「git 提交」统一成一个个可复习的内容单元（跳过空内容）。"""
    anchors: List[Anchor] = []
    block_paths = set(blocks)

    def add(anchor: Anchor) -> None:
        if anchor.content:
            anchors.append(anchor)

    # 1) 有日期标记的文件：每个日期块单独排复习
    for path, blist in blocks.items():
        for block in blist:
            stamp = block.key.split("@block:", 1)[-1]
            candidate = Anchor(path, block.learned, "block:%s" % stamp, "block", block=block)
            candidate.content = [ln for ln in block.lines if ln.strip()]
            add(candidate)

    # 2) 没有日期标记的文件：按 git 提交日期整篇排复习
    for path, dates in events.items():
        if path in block_paths:
            continue
        for day_str, commits in dates.items():
            try:
                learned = date.fromisoformat(day_str)
            except ValueError:
                continue
            candidate = Anchor(path, learned, day_str, "file", commits=commits)
            candidate.content = anchor_lines(candidate)
            add(candidate)

    anchors.sort(key=lambda a: (a.learned, a.path, a.anchor))
    return anchors


def _as_date(value: object) -> Optional[date]:
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


class Schedule(object):
    """某段内容当前「待复习的那一轮」。"""

    __slots__ = (
        "anchor", "round_no", "interval", "gap", "due",
        "overdue_days", "today", "index", "content",
    )

    def __init__(
        self,
        anchor: Anchor,
        round_no: int,
        interval: int,
        gap: int,
        due: date,
        today: date,
    ) -> None:
        self.anchor = anchor
        self.round_no = round_no        # 第几轮
        self.interval = interval        # 这一轮对应的间隔（也是记录用的 key）
        self.gap = gap                  # 距离上一轮过了几天
        self.due = due                  # 计划复习日
        self.today = today
        self.overdue_days = max(0, (today - due).days)
        self.index = 0
        self.content: Optional[List[str]] = None

    @property
    def path(self) -> str:
        return self.anchor.path

    @property
    def learned(self) -> date:
        return self.anchor.learned

    @property
    def location(self) -> str:
        return self.anchor.location

    @property
    def key(self) -> str:
        return self.anchor.key(self.interval)

    @property
    def is_today(self) -> bool:
        return self.due == self.today

    @property
    def is_future(self) -> bool:
        return self.due > self.today


def resolve_schedules(
    anchors: Sequence[Anchor],
    reviewed: Dict[str, str],
    today: date,
    with_content: bool = False,
) -> List[Schedule]:
    """
    算出每段内容当前待复习的那一轮。
    复习日 = 上一轮「实际」复习日 + 间隔差，所以晚一天复习后面的安排会自动顺延,
    不会一次冒出好几轮同样的内容。
    """
    schedules: List[Schedule] = []
    for anchor in anchors:
        done_idx = -1
        last_done: Optional[date] = None
        for i, interval in enumerate(INTERVALS):
            done = _as_date(reviewed.get(anchor.key(interval)))
            if done is None:
                break
            done_idx = i
            last_done = done

        nxt = done_idx + 1
        if nxt >= len(INTERVALS):
            continue  # 所有轮次都复习完了

        prev_interval = INTERVALS[nxt - 1] if nxt > 0 else 0
        base = last_done if (nxt > 0 and last_done is not None) else anchor.learned
        gap = INTERVALS[nxt] - prev_interval
        due = base + timedelta(days=gap)
        schedules.append(Schedule(anchor, nxt + 1, INTERVALS[nxt], gap, due, today))

    schedules.sort(key=lambda s: (s.due, s.path, s.round_no))

    if with_content:
        kept: List[Schedule] = []
        for s in schedules:
            s.content = s.anchor.content
            if s.content:
                kept.append(s)
        schedules = kept
    return schedules


def future_dues(schedule: Schedule, today: date, days: int) -> List[Tuple[date, int]]:
    """在「按时复习」的假设下，往后推算这段内容还会有的复习日。"""
    if schedule.overdue_days:
        return []  # 已经逾期，后面的时间没法可靠预测
    result: List[Tuple[date, int]] = []
    limit = today + timedelta(days=days)
    due = schedule.due
    idx = schedule.round_no - 1
    while idx + 1 < len(INTERVALS):
        due = due + timedelta(days=INTERVALS[idx + 1] - INTERVALS[idx])
        idx += 1
        if due > limit:
            break
        result.append((due, idx + 1))
    return result


def upcoming_map(
    schedules: Sequence[Schedule], today: date, days: int
) -> List[Tuple[date, List[str]]]:
    """未来 days 天内每天有哪些内容要复习。"""
    buckets: Dict[date, List[str]] = {}
    for s in schedules:
        for due, _round_no in future_dues(s, today, days):
            if due > today:
                buckets.setdefault(due, []).append(s.path)
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


def anchor_lines(anchor: Anchor) -> List[str]:
    """该复习项对应的内容行（已去掉空行）。"""
    if anchor.block is not None:
        return [ln for ln in anchor.block.lines if ln.strip()]

    collected: List[str] = []
    if anchor.commits:
        seen = set()
        for commit in anchor.commits:
            for line in added_lines(commit, anchor.path):
                if line in seen:
                    continue
                seen.add(line)
                collected.append(line)
    else:
        collected = read_file_lines(anchor.path)
    return [ln for ln in collected if ln.strip()]


# ==================== 输出 ====================


def fmt_date(d: date) -> str:
    return "%s %s" % (d.isoformat(), WEEKDAYS[d.weekday()])


def _width(text: str) -> int:
    """中文按 2 个宽度计算，用于对齐表格。"""
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)


def _fit(text: str, width: int) -> str:
    """按显示宽度截断并补齐空格。"""
    text = text.replace("|", "/")
    if _width(text) <= width:
        return text + " " * (width - _width(text))
    out: List[str] = []
    used = 0
    for ch in text:
        w = 2 if ord(ch) > 0x2E7F else 1
        if used + w > width - 2:
            break
        out.append(ch)
        used += w
    return "".join(out) + "…" + " " * max(0, width - used - 2)


def print_item(s: "Schedule", lines: Sequence[str], full: bool) -> None:
    print(" [%d] %s" % (s.index, s.path))
    print("     位置：%s │ 学习日期 %s" % (s.location, s.learned.isoformat()))
    print(
        "     第 %d 轮复习（距上一轮 %d 天）│ 计划复习日 %s"
        % (s.round_no, s.gap, s.due.isoformat())
    )
    if s.anchor.commits:
        print("     来源提交：%s" % ", ".join(s.anchor.commits))

    if not lines:
        print("     （没有可显示的内容，可能是只删不改，快速回忆一下即可）")
        print()
        return

    shown = lines if full else lines[:PREVIEW_LINES]
    print(
        "     ── 今天要复习的内容（共 %d 行%s）──"
        % (len(lines), "" if full else "，展示前 %d 行" % len(shown))
    )
    for ln in shown:
        print("       │ " + ln)
    if not full and len(lines) > len(shown):
        print("       │ ...（还有 %d 行，加 --full 查看全部）" % (len(lines) - len(shown)))
    print()


def print_overdue_table(overdue: Sequence["Schedule"]) -> None:
    print(SUB)
    print(" 🕒 逾期未复习：%d 项（只列清单，不展开内容）" % len(overdue))
    print()
    print(
        "   "
        + _fit("文件", TABLE_PATH_WIDTH)
        + " "
        + _fit("位置", TABLE_LOC_WIDTH)
        + " "
        + _fit("学习日期", 12)
        + " "
        + _fit("计划复习日", 12)
        + " "
        + "逾期"
    )
    for s in overdue:
        print(
            "   "
            + _fit(s.path, TABLE_PATH_WIDTH)
            + " "
            + _fit(s.location, TABLE_LOC_WIDTH)
            + " "
            + _fit(s.learned.isoformat(), 12)
            + " "
            + _fit(s.due.isoformat(), 12)
            + " "
            + "%d 天（第 %d 轮）" % (s.overdue_days, s.round_no)
        )
    print()


def write_overdue_file(overdue: Sequence["Schedule"], today: date) -> Optional[Path]:
    """把逾期清单写成 markdown 表格；没有逾期内容时删除该文件。"""
    path = REPO / OVERDUE_FILE
    if not overdue:
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        return None

    lines = [
        "# 逾期未复习清单",
        "",
        "> 更新时间：%s" % fmt_date(today),
        "> 每次运行 `python tools/review.py` 都会重新生成。",
        "",
        "| 文件 | 位置 | 学习日期 | 计划复习日 | 逾期天数 | 轮次 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for s in overdue:
        lines.append(
            "| `%s` | %s | %s | %s | %d 天 | 第 %d 轮 |"
            % (s.path, s.location, s.learned.isoformat(), s.due.isoformat(), s.overdue_days, s.round_no)
        )
    lines += [
        "",
        "复习完这些内容后，执行下面的命令把它们标记为已补复习：",
        "",
        "```",
        "python tools/review.py --catch-up",
        "```",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ==================== 提示 ====================


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
    anchors = build_anchors(events, blocks)
    schedules = resolve_schedules(anchors, reviewed, TODAY, with_content=True)
    todays = [s for s in schedules if s.is_today]
    overdue = [s for s in schedules if s.overdue_days > 0]

    print(BAR)
    print("   📚 今日复习   【%s】" % fmt_date(TODAY))
    print("   仓库：%s" % REPO)
    print(BAR)

    if todays:
        print()
        print(" 🔥 今天要复习 %d 段内容（看完就等于今天学完了）" % len(todays))
        for i, s in enumerate(todays, start=1):
            s.index = i
            print(SUB)
            print_item(s, s.content or [], full=args.full)
    else:
        print()
        print("   ✅ 今天没有到期的复习内容，去学点新东西吧～")
        print()

    if overdue:
        print_overdue_table(overdue)
        if args.show_overdue:
            print(" 📖 下面展开逾期内容的正文：")
            for i, s in enumerate(overdue, start=1):
                s.index = i
                print(SUB)
                print_item(s, s.content or [], full=args.full)

    upcoming = upcoming_map(schedules, TODAY, args.upcoming) if args.upcoming else []
    if upcoming:
        print(SUB)
        print(" 📅 未来 %d 天还会复习（按按时复习推算）" % args.upcoming)
        for d, paths in upcoming:
            print("     %s   %d 项" % (fmt_date(d), len(paths)))
        print()

    print_hint_uncommitted()

    log_path = write_overdue_file(overdue, TODAY)

    print(SUB)
    if todays and not args.no_mark:
        for s in todays:
            reviewed[s.key] = TODAY.isoformat()
        state["reviewed"] = reviewed
        save_state(state)
        print(
            " ✅ 已记账：今天这 %d 段内容记为「%s 已复习」，明天不会再提醒。"
            % (len(todays), TODAY.isoformat())
        )
    elif todays:
        print(" ℹ️  当前是「只看不记」（--no-mark），本次没有写入复习记录。")

    if overdue and log_path is not None:
        print(" 📄 逾期清单已写入 %s，复习完用 --catch-up 清掉。" % OVERDUE_FILE)
    if not todays and not overdue:
        print(" 🎉 目前没有任何待复习的内容。")
    print(" 提示：--no-mark 只看不记 / --catch-up 补复习 / --status 看后续安排 / --markers 检查日期标记")
    print(BAR)
    return 0


def command_done(args: argparse.Namespace, state: Dict[str, object]) -> int:
    reviewed: Dict[str, str] = state.get("reviewed", {})  # type: ignore[assignment]
    blocks = collect_blocks()
    events = collect_events()
    anchors = build_anchors(events, blocks)
    todays = [
        s
        for s in resolve_schedules(anchors, reviewed, TODAY, with_content=True)
        if s.is_today
    ]

    if not todays:
        print("✅ 今天没有待复习的项目，无需标记。")
        return 0

    for i, s in enumerate(todays, start=1):
        s.index = i

    if args.done == "all":
        targets = todays
    else:
        wanted = set()
        for chunk in str(args.done).split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                wanted.add(int(chunk))
        targets = [s for s in todays if s.index in wanted]
        if not targets:
            print("⚠️  没有匹配的项目，可用序号：1 ~ %d" % len(todays))
            return 1

    for s in targets:
        reviewed[s.key] = TODAY.isoformat()
    state["reviewed"] = reviewed
    save_state(state)

    print("✅ 已标记 %d 项为「今天复习完成」：" % len(targets))
    for s in targets:
        print("   · %s（%s，第 %d 轮）" % (s.path, s.location, s.round_no))
    return 0


def command_catch_up(args: argparse.Namespace, state: Dict[str, object]) -> int:
    """把逾期清单里的内容全部标记为「今天补复习完成」。"""
    reviewed: Dict[str, str] = state.get("reviewed", {})  # type: ignore[assignment]
    blocks = collect_blocks()
    events = collect_events()
    anchors = build_anchors(events, blocks)
    overdue = [
        s
        for s in resolve_schedules(anchors, reviewed, TODAY, with_content=True)
        if s.overdue_days > 0
    ]

    if not overdue:
        write_overdue_file([], TODAY)
        print("✅ 没有逾期未复习的内容，无需补记。")
        return 0

    for s in overdue:
        reviewed[s.key] = TODAY.isoformat()
    state["reviewed"] = reviewed
    save_state(state)
    write_overdue_file([], TODAY)

    print(
        "✅ 已把 %d 项逾期内容记为「%s 补复习完成」，后续复习从今天重新往后排："
        % (len(overdue), TODAY.isoformat())
    )
    for s in overdue:
        print(
            "   · %s（%s，第 %d 轮，原本 %s 到期，逾期 %d 天）"
            % (s.path, s.location, s.round_no, s.due.isoformat(), s.overdue_days)
        )
    print()
    print(" 现在运行 python tools/review.py 看看今天的任务吧。")
    return 0


def command_status(args: argparse.Namespace, state: Dict[str, object]) -> int:
    reviewed: Dict[str, str] = state.get("reviewed", {})  # type: ignore[assignment]
    blocks = collect_blocks()
    events = collect_events()
    anchors = build_anchors(events, blocks)
    schedules = resolve_schedules(anchors, reviewed, TODAY, with_content=True)

    by_path: Dict[str, List[Schedule]] = {}
    for s in schedules:
        by_path.setdefault(s.path, []).append(s)

    print(BAR)
    print("   📊 复习安排   【%s】" % fmt_date(TODAY))
    print(BAR)

    print(
        " · "
        + _fit("文件", 38)
        + " 状态"
    )
    today_total = overdue_total = 0
    for path in sorted(set(a.path for a in anchors)):
        units = by_path.get(path, [])
        if not units:
            print(" · " + _fit(path, 38) + " ✅ 全部复习完成")
            continue
        due = min(u.due for u in units)
        today_units = sum(1 for u in units if u.is_today)
        overdue_units = sum(1 for u in units if u.overdue_days > 0)
        today_total += today_units
        overdue_total += overdue_units
        if overdue_units:
            status = "🔔 今日 %d 段 + 逾期 %d 段" % (today_units, overdue_units)
        elif today_units:
            status = "🔔 今日要复习 %d 段" % today_units
        else:
            status = "%s 起复习 %d 段" % (due.isoformat(), len(units))
        print(" · " + _fit(path, 38) + " " + status)

    print()
    print(" 今天要复习 %d 段，逾期未复习 %d 段。" % (today_total, overdue_total))
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
                "    第 %d-%d 行 │ 标记 %-24s │ 学习 %s │ 内容 %d 行 │ 最后一轮 %s"
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
    print(
        "    %d年%d月%d日%d:%02d:%02d"
        % (now.year, now.month, now.day, now.hour, now.minute, now.second)
    )
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
    write_overdue_file([], TODAY)
    print("🧹 已清空 %d 条复习记录，所有内容将重新进入复习计划。" % count)
    return 0


# ==================== 入口 ====================

TODAY: date = date.today()


def main(argv: Optional[Sequence[str]] = None) -> int:
    global TODAY

    parser = argparse.ArgumentParser(
        description="艾宾浩斯复习提醒：跑一次 = 今天已学（并自动记账）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--no-mark", action="store_true",
                        help="只看今天的复习内容，不写入复习记录")
    parser.add_argument("--show-overdue", action="store_true",
                        help="把逾期内容的正文也展开显示（默认只列清单）")
    parser.add_argument("--catch-up", action="store_true",
                        help="把逾期清单里的内容全部记为「已补复习」")
    parser.add_argument("--done", nargs="?", const="all", metavar="序号",
                        help="标记今天已复习，可指定序号，如 --done 1,3；不带参数表示全部")
    parser.add_argument("--upcoming", type=int, default=None, metavar="N",
                        help="预告未来 N 天的复习安排（默认 %d 天，0 表示不显示）" % DEFAULT_UPCOMING)
    parser.add_argument("--status", action="store_true", help="查看每个文件的复习安排")
    parser.add_argument("--markers", action="store_true", help="列出识别到的日期标记（检查格式）")
    parser.add_argument("--stamp", action="store_true", help="生成当前时间戳，方便粘贴进笔记")
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
    if args.catch_up:
        return command_catch_up(args, state)
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
