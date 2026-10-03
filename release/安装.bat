@echo off
chcp 65001 >nul
echo ============================================
echo   红包乱斗 - 一键安装
echo ============================================
echo.
echo 本安装会把程序放到:
echo   %%LOCALAPPDATA%%\Programs\ARAM Score
echo 并创建 开始菜单 + 桌面 快捷方式。
echo (无需管理员权限，若要装到 Program Files 请右键"以管理员身份运行")
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1"
echo.
pause
