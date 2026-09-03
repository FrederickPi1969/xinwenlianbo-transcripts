#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重建索引：
- news/YYYY/catalogue.json  每年一册目录（date / file / source / story titles）
- README.md                 年份总表 + 最近 14 天（在标记之间原地重写）
"""

import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS_DIR = os.path.join(BASE_DIR, "news")
README_PATH = os.path.join(BASE_DIR, "README.md")
TZ = ZoneInfo("Asia/Shanghai")

STORY_RE = re.compile(r"^## (\d+)\. (.+)$", re.M)
SOURCE_RE = re.compile(r"^- 数据源：(.+)$", re.M)

BEGIN_YEARS, END_YEARS = "<!-- BEGIN:YEARS -->", "<!-- END:YEARS -->"
BEGIN_RECENT, END_RECENT = "<!-- BEGIN:RECENT -->", "<!-- END:RECENT -->"


def scan_year(year_dir):
    catalogue = []
    for fn in sorted(os.listdir(year_dir)):
        if not re.fullmatch(r"\d{8}\.md", fn):
            continue
        text = open(os.path.join(year_dir, fn), encoding="utf-8").read()
        titles = [t.strip() for _, t in STORY_RE.findall(text)]
        src_m = SOURCE_RE.search(text)
        src = "cctv" if src_m and "央视网" in src_m.group(1) else "govopendata"
        catalogue.append({
            "date": f"{fn[:4]}-{fn[4:6]}-{fn[6:8]}",
            "file": f"news/{year_dir[-4:]}/{fn}",
            "source": src,
            "stories": len(titles),
            "titles": titles,
        })
    catalogue.sort(key=lambda x: x["date"], reverse=True)
    with open(os.path.join(year_dir, "catalogue.json"), "w", encoding="utf-8") as fh:
        json.dump(catalogue, fh, ensure_ascii=False, indent=1)
    return catalogue


def rebuild_section(text, begin, end, block):
    pattern = re.compile(re.escape(begin) + r".*?" + re.escape(end), re.S)
    if not pattern.search(text):
        raise SystemExit(f"README 缺少标记 {begin}")
    return pattern.sub(begin + "\n" + block + "\n" + end, text, count=1)


def main():
    years = {}
    if os.path.isdir(NEWS_DIR):
        for entry in sorted(os.listdir(NEWS_DIR)):
            ydir = os.path.join(NEWS_DIR, entry)
            if re.fullmatch(r"(19|20)\d{2}", entry) and os.path.isdir(ydir):
                years[entry] = scan_year(ydir)

    total = sum(len(v) for v in years.values())

    years_rows = ["| 年份 | 天数 | 目录 |", "| --- | ---: | --- |"]
    for y in sorted(years, reverse=True):
        years_rows.append(f"| {y} | {len(years[y])} | [news/{y}/](news/{y}/) |")

    recent = []
    all_days = [rec for v in years.values() for rec in v]
    all_days.sort(key=lambda r: r["date"], reverse=True)
    for rec in all_days[:14]:
        recent.append(f"- [{rec['date']}](./{rec['file']}) — {rec['stories']} 条")

    text = open(README_PATH, encoding="utf-8").read()
    text = rebuild_section(text, BEGIN_YEARS, END_YEARS, "\n".join(years_rows))
    text = rebuild_section(text, BEGIN_RECENT, END_RECENT, "\n".join(recent))
    text = re.sub(r"<!-- UPDATED_AT -->.*?<!-- /UPDATED_AT -->",
                  f"<!-- UPDATED_AT -->{datetime.now(TZ).strftime('%Y-%m-%d %H:%M')} 北京时间<!-- /UPDATED_AT -->",
                  text, flags=re.S)
    with open(README_PATH, "w", encoding="utf-8") as fh:
        fh.write(text)

    print(f"索引完成：{total} 天，{len(years)} 个年份目录")


if __name__ == "__main__":
    main()
