# -*- coding: utf-8 -*-
"""
一键提交：把当前仓库的所有改动自动提交到 git
============================================
用法（在仓库根目录执行）：
    python tools/autocommit.py                    # 提交全部改动，消息自动生成
    python tools/autocommit.py -m "学了定语从句"    # 用自定义提交消息
    python tools/autocommit.py --push             # 提交后顺便 push 到远程
    python tools/autocommit.py --dry-run          # 只看会提交什么，不真的提交
    python tools/autocommit.py --status           # 查看当前有哪些改动

提交消息格式（自动生成时）：
    学习记录 2026-09-15 18:20
    - 新增：Grammar/从句/定语从句.md
    - 修改：Word/短语搭配.md
    - 删除：Grammar/句子骨架/旧笔记.md

也可以直接双击仓库根目录的「一键提交.bat」。
"""

import argparse
import subprocess
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# ==================== 配置区 ====================

# 自动生成提交消息时使用的前缀
MESSAGE_PREFIX = "学习记录"

# 是否默认执行 push（也可以在命令行用 --push 打开）
PUSH_BY_DEFAULT = False

# 提交消息里最多列多少个文件，超出则显示「等 N 个文件」
MAX_FILES_IN_MESSAGE = 15

# ==================== 基础工具 ====================


def setup_stdout() -> None:
    """尽量让 Windows 终端能正确显示中文。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


def find_repo_root() -> Path:
    here = Path(__file__).resolve().parent
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(here),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip())
    except OSError:
        pass
    return here.parent if here.name in ("tools", "scripts") else here


REPO = find_repo_root()


def git(*args: str, check: bool = False) -> Tuple[int, str, str]:
    """执行 git 命令，返回 (返回码, 标准输出, 标准错误)。"""
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotepath=false", *args],
            cwd=str(REPO),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        return 1, "", str(exc)
    out, err = proc.stdout or "", proc.stderr or ""
    if check and proc.returncode != 0:
        print("❌ git %s 执行失败：\n%s" % (" ".join(args), (err or out).strip()))
    return proc.returncode, out, err


def is_git_repo() -> bool:
    code, out, _ = git("rev-parse", "--is-inside-work-tree")
    return code == 0 and out.strip() == "true"


# ==================== 读取改动 ====================


def porcelain_entries() -> List[Tuple[str, str, str]]:
    """
    返回 [(状态码, 展示用路径, 真实路径)]。
    状态码取自 git status --porcelain 的前两列。
    """
    code, out, _ = git("status", "--porcelain", "-uall")
    if code != 0:
        return []

    entries: List[Tuple[str, str, str]] = []
    for raw in (out or "").splitlines():
        if len(raw) < 4:
            continue
        status, rest = raw[:2], raw[3:]
        real = rest
        if " -> " in rest:  # 重命名：取新路径
            old, real = rest.split(" -> ", 1)
            rest = "%s → %s" % (old.strip(), real.strip())
        real = real.strip().strip('"')
        entries.append((status, rest.strip(), real))
    return entries


def classify(status: str) -> str:
    """把 git 状态码翻译成中文动作。"""
    if status.strip() == "??":
        return "新增"
    if "R" in status:
        return "重命名"
    if "D" in status:
        return "删除"
    if "C" in status:
        return "复制"
    if "A" in status:
        return "新增"
    return "修改"


def summarize(entries: Sequence[Tuple[str, str, str]]) -> "OrderedDict[str, List[str]]":
    """按「新增 / 修改 / 删除 / 重命名 / 复制」分组。"""
    groups: "OrderedDict[str, List[str]]" = OrderedDict(
        (k, []) for k in ("新增", "修改", "重命名", "复制", "删除")
    )
    for status, display, _real in entries:
        groups[classify(status)].append(display)
    return OrderedDict((k, v) for k, v in groups.items() if v)


def build_message(groups: "OrderedDict[str, List[str]]", when: datetime) -> str:
    """生成提交消息：标题 + 按动作分组的文件列表。"""
    title = "%s %s" % (MESSAGE_PREFIX, when.strftime("%Y-%m-%d %H:%M"))
    lines = [title, ""]
    total = 0
    shown_total = 0
    for action, paths in groups.items():
        total += len(paths)
        shown = paths[:MAX_FILES_IN_MESSAGE]
        shown_total += len(shown)
        for i, path in enumerate(shown):
            lines.append("- %s：%s" % (action, path))
        if len(paths) > len(shown):
            lines.append("- %s：等共 %d 个文件" % (action, len(paths)))
    if total > shown_total:
        lines.append("")
        lines.append("共计 %d 个文件变动。" % total)
    return "\n".join(lines)


def show_status() -> int:
    entries = porcelain_entries()
    if not entries:
        print("📭 当前没有未提交的改动，工作区是干净的。")
        return 0
    groups = summarize(entries)
    print("📋 当前改动（共 %d 个文件）：" % len(entries))
    for action, paths in groups.items():
        print("  【%s】" % action)
        for path in paths:
            print("    · %s" % path)
    return 0


# ==================== 分支与远程 ====================


def current_branch() -> str:
    code, out, _ = git("rev-parse", "--abbrev-ref", "HEAD")
    return out.strip() if code == 0 and out.strip() else ""


def has_upstream() -> bool:
    code, _, _ = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    return code == 0


def has_remote() -> bool:
    code, out, _ = git("remote")
    return code == 0 and bool(out.strip())


# ==================== 主流程 ====================


def run(args: argparse.Namespace) -> int:
    now = datetime.now()

    if not is_git_repo():
        print("❌ 当前目录不是 git 仓库：%s" % REPO)
        return 2

    if args.status:
        return show_status()

    if args.pull:
        print("⬇️  先拉取远程更新（rebase）……")
        code, out, err = git("pull", "--rebase", "--autostash")
        text = (out or err).strip()
        if text:
            print(text)
        if code != 0:
            print("⚠️  pull 失败，已停止（可先手动处理冲突：git status）。")
            return 1

    entries = porcelain_entries()
    if not entries:
        print("📭 当前没有未提交的改动，无需提交。")
        if args.push:
            return do_push()
        return 0

    groups = summarize(entries)
    print("📋 检测到 %d 个文件有变动：" % len(entries))
    for action, paths in groups.items():
        print("  【%s】%d 个" % (action, len(paths)))
        for path in paths[:10]:
            print("    · %s" % path)
        if len(paths) > 10:
            print("    · ...还有 %d 个" % (len(paths) - 10))
    print()

    message = args.message.strip() if args.message else build_message(groups, now)
    print("📝 提交消息：")
    for line in message.splitlines():
        print("    " + line)
    print()

    if args.dry_run:
        print("🔍 --dry-run：以上内容不会真的提交。")
        return 0

    code, out, err = git("add", "-A")
    if code != 0:
        print("❌ git add 失败：\n%s" % (err or out).strip())
        return 1

    # 用 -F - 从标准输入读消息，避免中文 / 换行在不同终端的转义问题
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotepath=false", "commit", "-F", "-"],
            cwd=str(REPO), input=message,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        print("❌ git commit 执行失败：%s" % exc)
        return 1
    combined = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if combined:
        print(combined)
    if proc.returncode != 0:
        print("❌ 提交失败，请检查上面的输出。")
        return 1

    print("✅ 提交成功。")

    if args.push:
        return do_push()

    if not PUSH_BY_DEFAULT:
        print("ℹ️  还没有推送到远程。需要的话加 --push，例如：python tools/autocommit.py --push")
    return 0


def do_push() -> int:
    if not has_remote():
        print("ℹ️  仓库没有配置远程地址，跳过 push。")
        return 0

    branch = current_branch()
    if has_upstream():
        code, out, err = git("push")
    else:
        print("ℹ️  当前分支还没有关联远程分支，自动设置 origin/%s。" % branch)
        code, out, err = git("push", "-u", "origin", branch)

    text = ((out or "") + (err or "")).strip()
    if text:
        print(text)
    if code != 0:
        print("❌ push 失败，可稍后手动执行：git push")
        return 1
    print("🚀 已推送到远程。")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="一键提交当前仓库的所有改动到 git",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-m", "--message", help="自定义提交消息（不填则自动生成）")
    parser.add_argument("--push", action="store_true", help="提交后顺便推送到远程")
    parser.add_argument("--pull", action="store_true", help="提交前先 pull --rebase 拉取远程更新")
    parser.add_argument("--dry-run", action="store_true", help="只显示将要提交的内容，不真正提交")
    parser.add_argument("--status", action="store_true", help="只查看当前有哪些改动")
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    setup_stdout()
    sys.exit(main())
