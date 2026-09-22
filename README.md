# xyq_learning_english_notes

I will record my learning the road of English.Even i so low since of before,but no start，no recevie

## 目录结构

```
Grammar/     语法
Sentence/    句子理解
Word/        单词、短语
2026_daily_record/  每日学习记录
tools/       复习提醒脚本
```

## 每日复习怎么用

**每天只需要做一件事：**

```
python tools\review.py
```

它会：
1. 计算**今天需要复习的内容**（包含今日到期和逾期内容）；
2. 把这些任务写进 `复习任务表.md`；
3. 由你自己在当天标题下面手动填写一次“当天是否已复习”。

也可以直接双击仓库根目录的 `复习提醒.bat`。

### 学新内容时：写上日期标记

在 `Grammar/`、`Sentence/` 的笔记里，新内容前**另起一行**写当前时间（代表这段内容的学习时间）：

```
2026年9月15日18:02:27

这里写这次学到的内容……
可以写很多行，直到下一个日期标记为止
```

运行 `python tools\review.py --stamp` 可以直接打印当前时间戳，复制粘贴即可。

## 复习节奏（艾宾浩斯）

| 轮次 | 复习时间 |
| --- | --- |
| 第 1 轮 | 学习后 1 天 |
| 第 2 轮 | 第 1 轮复习后再过 1 天 |
| 第 3 轮 | 第 2 轮复习后再过 2 天 |
| 第 4 轮 | 第 3 轮复习后再过 3 天 |
| 之后 | 再过 8、15、30、60 天（累计 1/2/4/7/15/30/60/120 天） |

按时复习时，复习日正好是学习后第 1、2、4、7、15、30、60、120 天；
**偶尔漏了一天，后面的安排会自动顺延，不会一次冒出好几轮同一段内容。**
想改节奏就编辑 `tools/review.py` 里的 `INTERVALS`。

## 复习时间的两种来源

| 情况 | 复习时间依据 |
| --- | --- |
| `Grammar/`、`Sentence/` 里的文件 | 文件内写的日期标记（精确到每一段内容） |
| 其它文件（`Word/`、`2026_daily_record/` 等） | 该文件的 git 提交日期 |

所以：改了文件记得 commit（或者给新内容补上日期标记），脚本才知道有新内容要复习。

## 每天怎么记复习

运行：

```
python tools\review.py
```

脚本会更新 `复习任务表.md`。你只需要打开这个文件，在当天标题下面填写：

```
当天是否已复习：是
```

也支持：

```
是
已复习
√
yes
[x]
```

脚本下次运行时，会把这一天整组任务视为“已复习”，然后自动推到下一轮。

## 其它命令

```
python tools\review.py --status       # 每个文件接下来的复习安排
python tools\review.py --markers      # 列出识别到的日期标记（检查格式写对没）
python tools\review.py --upcoming 14  # 未来 14 天的复习量
python tools\review.py --full         # 复习内容完整显示，不截断
python tools\review.py --reset        # 清空复习记录，重新开始
```

说明：`--done`、`--catch-up`、`--no-mark` 是旧模式遗留参数，当前模式下不再负责自动记账。

## 一键提交（可选）

```
python tools\autocommit.py            # 自动生成提交信息并提交全部改动
python tools\autocommit.py --push     # 提交后顺便推送
```

也可以双击 `一键提交.bat`。

复习任务记录保存在 `复习任务表.md`；旧版 `.review_state.json` 只为兼容保留，不再作为主记录源。

## 验证脚本

改完 `tools/review.py` 或 `tools/autocommit.py` 后，可以运行：

```
python -m unittest discover -s tests -v
```

目前测试覆盖：日期标记识别、相对间隔复习节奏、手动复习表解析与合并、自动提交消息生成。
