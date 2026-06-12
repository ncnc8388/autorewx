@echo off
chcp 65001 >nul 2>&1
title 微信群消息监控自动回复

echo ============================================
echo   微信群消息监控自动回复工具
echo   (pywinauto 自包含方案，无需额外下载)
echo ============================================
echo.

:: 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 安装核心依赖
echo [步骤1] 安装依赖...
pip install pywinauto pillow 2>nul

echo.
echo ============================================
echo [提示] 请确保:
echo   1. 微信已打开并登录
echo   2. 微信窗口可见（未最小化）
echo   3. 微信处于主聊天页面
echo ============================================
echo.
echo 按任意键开始监控...
pause >nul

:: 启动主程序
python "%~dp0main.py"

echo.
echo 程序已退出
pause
