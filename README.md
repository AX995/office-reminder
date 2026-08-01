# 办公文件夹统一管理助手 - Windows EXE 打包

## 准备工作（在你的 Windows 电脑上）

1. 安装 Python 3.10+：https://www.python.org/downloads/
2. 把 `main.py`、`build.spec`、`build.bat` 放到同一个文件夹

## 方法一：一键打包（推荐）

双击运行 `build.bat`，等待完成即可。
EXE 在 `dist\办公助手.exe`

## 方法二：手动打包

```cmd
pip install pyside6 pyinstaller
pyinstaller build.spec --clean --noconfirm
```

## 输出文件

```
dist\
  └── 办公助手.exe    ← 这就是你的程序
```

## 可选：自定义图标

准备一个 `.ico` 图标文件放到文件夹里，然后修改 `build.spec` 中的 `icon='app_icon.ico'` 为你的图标文件名。

## 程序特点

- 单文件，无需安装 Python
- 关闭窗口自动最小化到托盘
- 支持三种任务：每日/每月固定日/间隔提醒
- 配置保存在同目录 `config.json`
