#!/usr/bin/env bash
# 一鍵更新資料並發布：重抓最新資料 → 重算預測 → 更新 docs/ → 推上線
# 用法：bash update.sh
set -e
cd "$(dirname "$0")"
PY=/home/lilian/miniconda3/bin/python3

echo "① 重抓資料、重算預測、更新 docs/（約 3~5 分鐘）..."
"$PY" daily_update.py

echo "② 發布到線上..."
bash publish.sh "資料更新 $(date '+%Y-%m-%d %H:%M')"
