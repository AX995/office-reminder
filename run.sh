#!/bin/sh
# 办公文件夹统一管理助手 - 启动脚本
# 在 Linux/macOS 桌面环境使用脚本启动本程序

cd "$(dirname "$0")"

# macOS 上可能需要设置此环境变量
if [ "$(uname)" = "Darwin" ]; then
    export QT_MAC_WANTS_LAYER=1
fi

python3 main.py
