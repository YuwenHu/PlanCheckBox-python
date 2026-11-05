@echo off
rem 开发态启动：需要本机已安装 Python 与 requirements.txt 依赖
cd /d "%~dp0"
python launch.py
if errorlevel 1 pause
