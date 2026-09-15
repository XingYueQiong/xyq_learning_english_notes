@echo off
chcp 65001 >nul
rem 双击即可把当前所有改动提交到 git（加参数 --push 可顺便推送）
python "%~dp0tools\autocommit.py" --push %*
pause
