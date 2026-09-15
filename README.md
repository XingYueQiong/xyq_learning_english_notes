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

1. 学新内容时，在笔记里**另起一行**写上当前时间（代表这段内容的“学习时间”）：

   ```
   2026年9月15日18:02:27

   这里写这次学到的内容……
   可以写很多行，直到下一个日期标记为止
   ```

   直接运行 `python tools\review.py --stamp` 可以打印出当前时间，复制粘贴即可。

2. 每天跑一次脚本，看今天该复习哪些内容（内容会直接打印出来）：

   ```
   python tools\review.py
   ```

   或者直接双击仓库根目录的 `复习提醒.bat`。

3. 复习完标记一下，这样不会再重复提醒：

   ```
   python tools\review.py --done        # 全部完成
   python tools\review.py --done 1,3    # 只完成第 1、3 项
   ```

## 复习节奏（艾宾浩斯）

每段内容在学习后的第 **1、2、4、7、15、30、60、120** 天安排复习。
想改节奏就编辑 `tools/review.py` 里的 `INTERVALS`。

## 复习时间的两种来源

| 情况 | 复习时间依据 |
| --- | --- |
| `Grammar/`、`Sentence/` 里的文件 | 文件内写的日期标记（可精确到每一段内容） |
| 其它文件（`Word/`、`2026_daily_record/` 等） | 该文件的 git 提交日期 |

所以：改了文件记得 `git commit`（或者给新内容补上日期标记），脚本才知道有新内容要复习。

## 其它命令

```
python tools\review.py --status      # 每个文件 / 每段内容的下次复习时间
python tools\review.py --markers     # 列出识别到的日期标记（检查格式写对没）
python tools\review.py --upcoming 14 # 未来 14 天的复习量
python tools\review.py --full        # 复习内容完整显示，不截断
python tools\review.py --reset       # 清空复习记录，重新开始
```

复习进度保存在 `.review_state.json`（不会提交到 git）。
