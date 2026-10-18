@echo off
REM KB Workbench - Windows start script
REM 双击即可启动；首次运行会自动建立全文索引。
cd /d "%~dp0"
if not defined KB_PORT set KB_PORT=17321
REM 知识库数据已迁至 E:\4个人知识库\vault（2026-10-17）
if not defined KB_VAULT set KB_VAULT=E:\4个人知识库\vault
echo.
echo   KB Workbench 启动中 ...
echo   打开浏览器访问:  http://localhost:%KB_PORT%
echo   （换端口: 先 set KB_PORT=9001 再运行本脚本）
echo   （按 Ctrl+C 停止服务）
echo.
python backend/app.py
pause
