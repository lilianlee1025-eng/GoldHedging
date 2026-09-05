#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""前端檢查：推上線前先跑這支，避免推了才發現網頁壞掉。

檢查三件事：
1. JS 語法（用 esprima 真正解析，不是數括號——數括號抓不到「少一個逗號」）
2. HTML 標籤是否配對
3. 模板用到的 {{ 變數 }} 是否都有在 renderVals 提供

用法：python3 check_frontend.py
"""
import io, re, sys

PATH = "docs/index.html"
s = io.open(PATH, encoding="utf-8").read()
m = re.search(r'<script type="text/x-dc"[^>]*>(.*?)</script>', s, re.S)
js = m.group(1)
line_off = s[: m.start(1)].count("\n")
html = s.split('<script type="text/x-dc"')[0]

fail = 0

# --- 1. JS 語法 ---
try:
    import esprima
    try:
        esprima.parseScript(js)
        print("✅ JS 語法正確")
    except Exception as e:
        fail = 1
        ln = getattr(e, "lineNumber", 0)
        print("❌ JS 語法錯誤：%s（%s 第 %d 行）" % (e, PATH, ln + line_off))
        rows = js.split("\n")
        for i in range(max(0, ln - 3), min(len(rows), ln + 2)):
            print("   %s %5d | %s" % (">>" if i == ln - 1 else "  ", i + 1 + line_off, rows[i]))
except ImportError:
    print("⚠️  未安裝 esprima，跳過語法檢查（pip install esprima）")

# --- 2. HTML 標籤配對 ---
bad = []
for tag in ("sc-if", "sc-for", "div", "span", "label", "table", "tr", "td", "th", "p"):
    o = len(re.findall(r"<%s[ >]" % tag, html))
    c = len(re.findall(r"</%s>" % tag, html))
    if o != c:
        bad.append("%s 開%d/關%d" % (tag, o, c))
if bad:
    fail = 1
    print("❌ 標籤不配對：" + "、".join(bad))
else:
    print("✅ HTML 標籤配對")

# --- 3. 模板變數是否有提供 ---
# renderVals 的 return 物件裡的鍵，加上 sc-for 的迴圈變數
used = set(re.findall(r"\{\{\s*([A-Za-z_]\w*)", html))
loop_vars = set(re.findall(r'<sc-for[^>]*\bas="(\w+)"', html))
provided = set(re.findall(r"^\s{6}([A-Za-z_]\w*)\s*:", js, re.M))
provided |= set(re.findall(r"\b([A-Za-z_]\w*)\s*:\s*[A-Za-z_$]", js))
missing = sorted(v for v in used if v not in provided and v not in loop_vars
                 and v not in {"true", "false"})
if missing:
    print("⚠️  模板變數可能未提供（也可能是誤報，請人工確認）：" + "、".join(missing))
else:
    print("✅ 模板變數都有提供")

sys.exit(fail)
