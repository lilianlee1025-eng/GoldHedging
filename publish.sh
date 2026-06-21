#!/usr/bin/env bash
# 一鍵發布：把本機改動更新到線上網站
# 用法：
#   bash publish.sh                 # 用預設訊息發布
#   bash publish.sh "我改了標題"     # 自訂這次的說明
set -e
cd "$(dirname "$0")"                 # 切到專案資料夾

MSG="${1:-更新內容 $(date '+%Y-%m-%d %H:%M')}"   # 沒給訊息就用日期時間

echo "① 先抓雲端最新（避免衝突）..."
git pull --no-edit origin main

echo "② 加入所有改動..."
git add -A

if git diff --cached --quiet; then
  echo "沒有任何改動，不需發布。"
  exit 0
fi

echo "③ 建立紀錄並推送..."
git commit -m "$MSG"
git push origin main

echo ""
echo "✅ 已發布！約 1 分鐘後線上更新："
echo "   https://lilianlee1025-eng.github.io/GoldHedging/"
