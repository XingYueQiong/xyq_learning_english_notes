# -*- coding: utf-8 -*-
"""
艾宾浩斯记忆曲线复习提醒
========================
根据本仓库的 git 提交历史，找出「今天该复习哪些文件、以及该复习的具体内容变更」。

用法（在仓库根目录执行）：
    python tools/review.py                    # 查看今天要复习的内容
    python tools/review.py --done             # 复习完成后，标记今天所有项目为已复习
    python tools/review.py --done 1,3         # 只标记第 1、3 项
    python tools/review.py --upcoming 14      # 查看未来 14 天的复习安排
    python tools/review.py --status           # 查看每个文件的下一次复习时间
    python tools/review.py --full             # 显示完整的变更内容（不截断）
    python tools/review.py --reset            # 清空复习记录，重新开始
    python tools/review.py --date 2026-09-20  # 假装今天是某一天（测试用）

原理：
    1. 用 `git log --name-status` 取出每个文件每次被修改的日期；
    2. 每次修改视为一次「学习事件」，按艾宾浩斯曲线在 1/2/4/7/15/30/60/120 天后安排复习；
    3. 已经复习过的（记在 .review_state.json 里）不会重复提醒；
    4. 未提交的改动不会被计入，请先 commit，脚本才会把它纳入计划。
"""

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# ==================== 配置区（可按需修改）====================

# 艾宾浩斯复习间隔（天）。想更密集就改成 [1, 2, 3, 5, 8, 13] 之类的
INTERVALS = [1, 2, 4, 7, 15, 30, 60, 120]

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


# ==================== 采集「学习事件」 ====================


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
    path = state_path()
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def item_key(path: str, learned: str, interval: int) -> str:
    return "%s@%s#%d" % (path, learned, interval)


# ==================== 生成复习计划 ====================


class ReviewItem(object):
    __slots__ = ("path", "learned", "interval", "due", "commits", "index")

    def __init__(self, path: str, learned: date, interval: int, commits: List[str]) -> None:
        self.path = path
        self.learned = learned
        self.interval = interval
        self.due = learned + timedelta(days=interval)
        self.commits = commits
        self.index = 0

    @property
    def key(self) -> str:
        return item_key(self.path, self.learned.isoformat(), self.interval)

    @property
    def round_no(self) -> int:
        return INTERVALS.index(self.interval) + 1


def build_items(
    events: Dict[str, Dict[str, List[str]]], reviewed: Dict[str, str]
) -> List[ReviewItem]:
    """所有到期的（含逾期）复习项，按时间升序。"""
    items: List[ReviewItem] = []
    for path, dates in events.items():
        for day_str, commits in dates.items():
            try:
                learned = date.fromisoformat(day_str)
            except ValueError:
                continue
            for interval in INTERVALS:
                item = ReviewItem(path, learned, interval, commits)
                if item.key in reviewed:
                    continue
                items.append(item)
    items.sort(key=lambda it: (it.due, it.learned, it.path, it.interval))
    return items


def upcoming_map(
    events: Dict[str, Dict[str, List[str]]], reviewed: Dict[str, str], today: date, days: int
) -> List[Tuple[date, int, List[str]]]:
    """未来 days 天内每天有多少项要复习。"""
    buckets: Dict[date, List[str]] = {}
    limit = today + timedelta(days=days)
    for path, dates in events.items():
        for day_str, _commits in dates.items():
            try:
                learned = date.fromisoformat(day_str)
            except ValueError:
                continue
            for interval in INTERVALS:
                due = learned + timedelta(days=interval)
                if not (today < due <= limit):
                    continue
                if item_key(path, day_str, interval) in reviewed:
                    continue
                buckets.setdefault(due, []).append(path)
    return [(d, len(v), sorted(set(v))) for d, v in sorted(buckets.items())]


# ==================== 提取「内容变更」 ====================


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


def change_lines(item: ReviewItem) -> List[str]:
    """带顺序去重的内容变更。"""
    if not item.commits:
        return read_file_lines(item.path)
    collected: List[str] = []
    seen = set()
    for commit in item.commits:
        for line in added_lines(commit, item.path):
            if line in seen:
                continue
            seen.add(line)
            collected.append(line)
    return collected


# ==================== 输出 ====================


def fmt_date(d: date) -> str:
    return "%s %s" % (d.isoformat(), WEEKDAYS[d.weekday()])


def print_item(item: ReviewItem, lines: Sequence[str], full: bool) -> None:
    overdue = item.due < TODAY
    flag = "⏰ 逾期 %d 天" % (TODAY - item.due).days if overdue else "🔥 今日到期"
    print(" [%d] %s" % (item.index, item.path))
    print(
        "     %s │ 学习日期 %s │ 第 %d 次复习（学习后 %d 天）"
        % (flag, item.learned.isoformat(), item.round_no, item.interval)
    )
    if item.commits:
        print("     来源提交：%s" % ", ".join(item.commits))
    body = [ln for ln in lines if ln.strip()]
    fallback = False
    if not body:
        # 该次提交只是移动 / 重命名文件：退回展示文件当前内容
        body = [ln for ln in read_file_lines(item.path) if ln.strip()]
        fallback = True
    if not body:
        print("     （本次提交仅移动 / 重命名文件，且当前无内容，扫一眼即可）")
    else:
        shown = body if full else body[:PREVIEW_LINES]
        if fallback:
            print("     ── 本次提交仅移动 / 重命名，下面是文件当前内容（共 %d 行）──" % len(body))
        else:
            print(
                "     ── 需要复习的内容（共 %d 行%s）──"
                % (len(body), "" if full else "，展示前 %d 行" % len(shown))
            )
        for ln in shown:
            print("       │ " + ln)
        if not full and len(body) > len(shown):
            print("       │ ...（还有 %d 行，加 --full 查看全部）" % (len(body) - len(shown)))
    print()


def command_report(args: argparse.Namespace, state: Dict[str, object]) -> int:
    events = collect_events()
    reviewed: Dict[str, str] = state.get("reviewed", {})  # type: ignore[assignment]
    items = [it for it in build_items(events, reviewed) if it.due <= TODAY]

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
        print_item(item, change_lines(item), full=args.full)

    upcoming = upcoming_map(events, reviewed, TODAY, args.upcoming)
    if upcoming:
        print(SUB)
        print(" 📅 未来 %d 天预告（只统计数量）" % args.upcoming)
        for d, count, _paths in upcoming:
            print("     %s   %d 项" % (fmt_date(d), count))
        print()

    pending_uncommitted = uncommitted_files()
    if pending_uncommitted:
        print(SUB)
        print(" ✍️  以下文件有未提交的改动，提交后才会纳入复习计划：")
        for path in pending_uncommitted:
            print("     · %s" % path)
        print()

    print(SUB)
    if items:
        print(" 本次共 %d 项待复习。复习完成后执行：python tools/review.py --done" % len(items))
    print(" 提示：--done 标记已完成 / --upcoming N 看预告 / --status 看每个文件的安排")
    print(BAR)
    return 0


def command_done(args: argparse.Namespace, state: Dict[str, object]) -> int:
    events = collect_events()
    reviewed: Dict[str, str] = state.get("reviewed", {})  # type: ignore[assignment]
    items = [it for it in build_items(events, reviewed) if it.due <= TODAY]

    if not items:
        print("✅ 今天没有待复习的项目，无需标记。")
        return 0

    if args.done == "all":
        targets = items
    else:
        wanted = set()
        for chunk in str(args.done).split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                wanted.add(int(chunk))
        for i, item in enumerate(items, start=1):
            item.index = i
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
        print("   · %s（学习日 %s，第 %d 次复习）" % (item.path, item.learned.isoformat(), item.round_no))
    print("\n记录已保存到 %s" % state_path())
    return 0


def command_status(args: argparse.Namespace, state: Dict[str, object]) -> int:
    events = collect_events()
    reviewed: Dict[str, str] = state.get("reviewed", {})  # type: ignore[assignment]

    print(BAR)
    print("   📊 各文件复习安排   【%s】" % fmt_date(TODAY))
    print(BAR)

    today_due = 0
    for path in sorted(events):
        dates = sorted(events[path])
        next_due: Optional[date] = None
        next_interval = 0
        for day_str in dates:
            learned = date.fromisoformat(day_str)
            for interval in INTERVALS:
                if item_key(path, day_str, interval) in reviewed:
                    continue
                due = learned + timedelta(days=interval)
                if next_due is None or due < next_due:
                    next_due, next_interval = due, interval
        if next_due is None:
            continue
        if next_due <= TODAY:
            today_due += 1
            status = "🔔 今天该复习（第 %d 轮）" % (INTERVALS.index(next_interval) + 1)
        else:
            status = "下次复习 %s（还有 %d 天）" % (next_due.isoformat(), (next_due - TODAY).days)
        print(" · %-40s 学习 %d 次 | %s" % (path, len(dates), status))
    print()
    print(" 今天共 %d 个文件需要复习。" % today_due)
    print(BAR)
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
    print("🧹 已清空 %d 条复习记录，所有历史提交将重新进入复习计划。" % count)
    return 0


# ==================== 入口 ====================

TODAY: date = date.today()


def main(argv: Optional[Sequence[str]] = None) -> int:
    global TODAY

    parser = argparse.ArgumentParser(
        description="艾宾浩斯记忆曲线复习提醒（基于 git 提交历史）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--done", nargs="?", const="all", metavar="序号",
                        help="标记今天已复习，可指定序号，如 --done 1,3；不带参数表示全部")
    parser.add_argument("--upcoming", type=int, default=None, metavar="N",
                        help="预告未来 N 天的复习安排（默认 %d 天）" % DEFAULT_UPCOMING)
    parser.add_argument("--status", action="store_true", help="查看每个文件的下一次复习安排")
    parser.add_argument("--reset", action="store_true", help="清空复习记录")
    parser.add_argument("--yes", action="store_true", help="--reset 时跳过确认")
    parser.add_argument("--full", action="store_true", help="显示完整的变更内容，不截断")
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

    if not REPO.exists() or not (REPO / ".git").exists():
        print("⚠️  当前目录不是 git 仓库，脚本将只能按文件修改时间估算。")

    state = load_state()

    if args.reset:
        return command_reset(args, state)
    if args.done:
        return command_done(args, state)
    if args.status:
        return command_status(args, state)
    return command_report(args, state)


if __name__ == "__main__":
    setup_stdout()
    sys.exit(main())
