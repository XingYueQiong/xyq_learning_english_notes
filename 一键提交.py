# -*- coding: utf-8 -*-

import argparse
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List


INTERVALS = [1, 2, 4, 7, 15, 30, 60, 120]
ROOT = Path(__file__).resolve().parent
DAILY_ROOT = ROOT / "2026_daily_record"
REVIEW_TITLE = "复习日期（艾宾浩斯）："


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and proc.returncode != 0:
        sys.stderr.write(proc.stderr or proc.stdout)
        raise SystemExit(proc.returncode)
    return proc


def current_branch() -> str:
    proc = run_git("rev-parse", "--abbrev-ref", "HEAD")
    branch = proc.stdout.strip()
    if not branch:
        raise SystemExit("无法识别当前分支。")
    return branch


def review_block(today: date) -> str:
    lines = [REVIEW_TITLE]
    for days in INTERVALS:
        lines.append("- %s" % (today + timedelta(days=days)).isoformat())
    return "\n".join(lines)


def today_record_path(today: date) -> Path:
    preferred = DAILY_ROOT / today.strftime("%B") / today.strftime("%m%d")
    if preferred.exists():
        return preferred

    candidates = [path for path in DAILY_ROOT.rglob(today.strftime("%m%d")) if path.is_file()]
    if candidates:
        return sorted(candidates)[0]

    preferred.parent.mkdir(parents=True, exist_ok=True)
    return preferred


def update_today_record(today: date) -> Path:
    path = today_record_path(today)
    original = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    marker = "\n" + REVIEW_TITLE
    new_block = review_block(today)

    if REVIEW_TITLE in original:
        head, _sep, _tail = original.partition(REVIEW_TITLE)
        body = head.rstrip()
        updated = (body + "\n\n" + new_block + "\n") if body else (new_block + "\n")
    else:
        body = original.rstrip()
        updated = (body + "\n\n" + new_block + "\n") if body else (new_block + "\n")

    if updated != original:
        path.write_text(updated, encoding="utf-8")
    return path


def has_staged_changes() -> bool:
    proc = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode == 1


def commit_message(now: datetime) -> str:
    return now.strftime("notes update %Y-%m-%d %H:%M:%S")


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args(argv)

    now = datetime.now()
    today = now.date()
    record = update_today_record(today)
    print("已更新：%s" % record.relative_to(ROOT).as_posix())

    if args.prepare_only:
        return 0

    branch = current_branch()
    run_git("add", "-A")
    if not has_staged_changes():
        print("没有需要提交的内容。")
        return 0

    run_git("commit", "-m", commit_message(now))
    push = run_git("push", "origin", branch)
    sys.stdout.write(push.stdout)
    sys.stderr.write(push.stderr)
    return push.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))