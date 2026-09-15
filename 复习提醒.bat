@echo off
chcp 65001 >nul
rem 双击即可查看今天要复习的内容
python "%~dp0tools\review.py" %*
pause
