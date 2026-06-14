#!/bin/bash
# 打包 Agnes AI 创作工具为独立可执行文件
# 用法: bash build.sh

set -e

echo "=== 安装依赖 ==="
pip install pyinstaller pillow --quiet

echo "=== 打包中 ==="
pyinstaller \
    --onefile \
    --windowed \
    --name "Agnes-AI" \
    --add-data ".env:." \
    --clean \
    app.py

echo ""
echo "=== 完成 ==="
echo "可执行文件在: dist/Agnes-AI"
echo "直接双击运行即可，无需安装 Python"
