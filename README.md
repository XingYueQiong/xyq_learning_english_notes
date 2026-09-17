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
1. 把**今天该复习的内容完整打印出来**（这就是今天的复习任务）；
2. 自动把今天这些内容记为「今天已复习」，明天不会再重复提醒；
3. 如果有**逾期没复习**的，列成一张表格（同时写入 `复习逾期清单.md`），不占用屏幕。

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

## 漏了几天怎么办

逾期内容会出现在 `复习逾期清单.md` 里（控制台也会显示一张表）。  
看完之后执行一次，把它们记为「今天补复习完成」，后续节奏从今天重新往后排：

```
python tools\review.py --catch-up
```

## 其它命令

```
python tools\review.py --no-mark      # 只看今天的复习内容，不记账
python tools\review.py --catch-up     # 逾期内容一次性补记
python tools\review.py --status       # 每个文件接下来的复习安排
python tools\review.py --markers      # 列出识别到的日期标记（检查格式写对没）
python tools\review.py --upcoming 14  # 未来 14 天的复习量
python tools\review.py --full         # 复习内容完整显示，不截断
python tools\review.py --reset        # 清空复习记录，重新开始
```

## 一键提交（可选）

```
python tools\autocommit.py            # 自动生成提交信息并提交全部改动
python tools\autocommit.py --push     # 提交后顺便推送
```

也可以双击 `一键提交.bat`。

复习进度保存在 `.review_state.json`，逾期清单在 `复习逾期清单.md`，这两个文件都不会提交到 git。
