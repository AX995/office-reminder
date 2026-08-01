@echo off
chcp 65001 >nul
echo ========================================
echo   办公文件夹统一管理助手 - 一键打包
echo ========================================
echo.

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/3] 安装依赖库...
pip install pyside6 pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败，请检查网络连接
    pause
    exit /b 1
)

echo.
echo [2/3] 开始打包（预计 3-10 分钟）...
pyinstaller build.spec --clean --noconfirm
if %errorlevel% neq 0 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

echo.
echo [3/3] 打包完成！
echo.
echo EXE 文件位置: %cd%\dist\办公助手.exe
echo.
echo 可以直接运行或复制到任意位置使用。
echo.

start explorer "%cd%\dist"
pause
