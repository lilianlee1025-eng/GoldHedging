#!/usr/bin/env bash
# 每日更新黃金避險資料（給 cron 排程用）
# 用法：手動測試 `bash run_daily.sh`；或加入 crontab 每天自動跑（見 README 第 11 節）。
set -e
cd "$(dirname "$0")"                       # 切到專案根目錄
PY=/home/lilian/miniconda3/bin/python3     # 指定 conda 的 Python
mkdir -p logs
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 開始每日更新 =====" >> logs/daily_update.log
"$PY" daily_update.py >> logs/daily_update.log 2>&1
echo "===== $(date '+%Y-%m-%d %H:%M:%S') 更新完成 =====" >> logs/daily_update.log
