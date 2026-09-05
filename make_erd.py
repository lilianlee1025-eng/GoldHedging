# -*- coding: utf-8 -*-
"""產生 ERD 圖檔（PNG）。
GitHub 上的 Mermaid 圖是瀏覽器即時渲染的向量圖，無法直接右鍵存成圖片，
所以這支程式用 Pillow 直接畫一張可以放進報告的點陣圖。
設計成黑白列印也清楚：用線條粗細與底色深淺區分，不倚賴顏色。
"""
from PIL import Image, ImageDraw, ImageFont

FONT = "/home/lilian/GoldHedging/data/fonts/NotoSansCJKtc-Regular.otf"
W, H = 2100, 1500
BG, INK, GREY = "#FFFFFF", "#1B211E", "#6B736E"
HDR, HDR_HI = "#2F3A34", "#8A6D1F"      # 一般表頭 / 重點表(positions)表頭
ROW_A, ROW_B = "#FFFFFF", "#F5F6F5"

f_title = ImageFont.truetype(FONT, 44)
f_sub   = ImageFont.truetype(FONT, 24)
f_tbl   = ImageFont.truetype(FONT, 30)
f_col   = ImageFont.truetype(FONT, 23)
f_rel   = ImageFont.truetype(FONT, 25)
f_note  = ImageFont.truetype(FONT, 21)

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

ROW_H, PAD = 40, 14

def table(x, y, w, name, note, cols, hi=False):
    """畫一張表，回傳 (左,上,右,下) 方便拉線。"""
    head_h = 62
    h = head_h + len(cols) * ROW_H
    d.rectangle([x, y, x + w, y + h], fill="#FFFFFF", outline=INK, width=3)
    d.rectangle([x, y, x + w, y + head_h], fill=HDR_HI if hi else HDR)
    d.text((x + PAD, y + 12), name, font=f_tbl, fill="#FFFFFF")
    tw = d.textlength(note, font=f_note)
    d.text((x + w - PAD - tw, y + 22), note, font=f_note, fill="#D8DCD9")
    for i, (c, kind) in enumerate(cols):
        ry = y + head_h + i * ROW_H
        d.rectangle([x + 1, ry, x + w - 1, ry + ROW_H], fill=ROW_A if i % 2 == 0 else ROW_B)
        tag = {"PK": "PK", "FK": "FK", "PKFK": "PK,FK"}.get(kind, "")
        d.text((x + PAD, ry + 8), c, font=f_col, fill=INK)
        if tag:
            twd = d.textlength(tag, font=f_col)
            d.text((x + w - PAD - twd, ry + 8), tag, font=f_col, fill=HDR_HI)
        d.line([x + 1, ry, x + w - 1, ry], fill="#E2E5E3", width=1)
    # 外框最後再描一次：先畫框再填色會被最後一列的底色蓋掉下緣
    d.rectangle([x, y, x + w, y + h], outline=INK, width=3)
    return (x, y, x + w, y + h)

# ---- 標題 ----
d.text((60, 44), "黃金避險決策系統 — 資料庫關聯圖（ERD）", font=f_title, fill=INK)
d.text((62, 104), "PostgreSQL / Supabase　·　auth schema 由平台管理，public schema 為本系統自建",
       font=f_sub, fill=GREY)

# ---- 父表 ----
users = table(760, 170, 580, "auth.users", "Supabase 內建", [
    ("id", "PK"), ("email", ""), ("encrypted_password", ""),
    ("last_sign_in_at", ""), ("created_at", ""),
])
sess = table(1560, 170, 480, "auth.sessions", "Supabase 內建", [
    ("id", "PK"), ("user_id", "FK"), ("not_after", ""),
])

# ---- 子表 ----
prof = table(70, 800, 560, "profiles", "風險偏好", [
    ("user_id", "PKFK"), ("risk_profile", ""), ("hedge_months", ""),
    ("hedge_vol", ""), ("hedge_rate", ""), ("updated_at", ""),
])
pos = table(710, 800, 660, "positions", "持有部位 ★", [
    ("id", "PK"), ("user_id", "FK"), ("label", ""), ("kind", ""),
    ("qty", ""), ("unit", ""), ("cost_per_oz", ""), ("updated_at", ""),
], hi=True)
uip = table(1450, 800, 580, "ui_prefs", "介面偏好", [
    ("user_id", "PKFK"), ("price_unit", ""), ("timeframe", ""),
    ("chart_type", ""), ("qty_unit", ""),
])

# ---- 關聯線 ----
BUS = 700
ucx, uby = (users[0] + users[2]) // 2, users[3]
d.line([ucx, uby, ucx, BUS], fill=INK, width=3)

def crow(x, y, many):
    """在子表上緣畫記號：多的一端畫鳥爪，一的一端畫短橫線。"""
    if many:
        d.line([x, y, x - 22, y - 26], fill=INK, width=3)
        d.line([x, y, x + 22, y - 26], fill=INK, width=3)
        d.line([x, y, x, y - 26], fill=INK, width=3)
    else:
        d.line([x - 18, y - 20, x + 18, y - 20], fill=INK, width=3)

for box, many, label in ((prof, False, "1 : 1"), (pos, True, "1 : N"), (uip, False, "1 : 1")):
    cx = (box[0] + box[2]) // 2
    d.line([ucx, BUS, cx, BUS], fill=INK, width=3)
    d.line([cx, BUS, cx, box[1]], fill=INK, width=3)
    crow(cx, box[1], many)
    tw = d.textlength(label, font=f_rel)
    d.rectangle([cx - tw // 2 - 10, BUS + 16, cx + tw // 2 + 10, BUS + 54], fill=BG)
    d.text((cx - tw // 2, BUS + 18), label, font=f_rel, fill=HDR_HI if many else INK)

# auth.users → auth.sessions（1:N，畫在右上）
d.line([users[2], 250, sess[0], 250], fill=GREY, width=3)
d.line([sess[0], 250, sess[0] - 22, 250 - 20], fill=GREY, width=3)
d.line([sess[0], 250, sess[0] - 22, 250 + 20], fill=GREY, width=3)
d.text((users[2] + 24, 206), "1 : N", font=f_rel, fill=GREY)

# ---- 說明 ----
y0 = 1290
d.line([60, y0 - 22, W - 60, y0 - 22], fill="#D8DCD9", width=2)
for i, t in enumerate([
    "★ positions 是唯一的一對多：一位使用者可同時持有金條（台錢）、黃金存摺（公克）、ETF（股）、金幣（盎司），各自有數量與成本。",
    "所有 user_id 皆為 references auth.users(id) on delete cascade —— 刪除帳號時相關資料自動清除。",
    "三張 public 表均啟用 Row Level Security，各有 4 條政策（SELECT/INSERT/UPDATE/DELETE），條件為 auth.uid() = user_id。",
]):
    d.text((60, y0 + i * 36), t, font=f_note, fill=GREY if i else INK)

img.save("docs/ERD.png")          # 放 docs/ 才會進版控（.gitignore 排除 outputs/*.png）
img.resize((W // 2, H // 2), Image.LANCZOS).save("outputs/ERD_small.png")
print("已產生 docs/ERD.png (%dx%d)" % (W, H))
