#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
列表驱动源的深回填：White House briefings-statements 与 State.gov press-releases。
这两个源按列表翻页发现条目（日期在卡片上），逐日抓反而要反复翻页，故单独走一遍。

用法：
    python3 listing_backfill.py --source wh --start 2025-01-01 --end 2026-09-03
    python3 listing_backfill.py --source state            # 全部翻完（不设范围）
"""

import argparse
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from global_daily import (http_get, strip_html, write_md, sleep_a_bit, FetchError, log)  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WH_ITEM_RE = re.compile(
    r'<a href="(https://www\.whitehouse\.gov/briefings-statements/\d{4}/\d{2}/[a-z0-9-]+)/?"[^>]*>([^<]{5,200})</a>')
STATE_CARD_RE = re.compile(
    r'<p class="collection-result__date">([^<]+)</p>\s*'
    r'<a href="(https://www\.state\.gov/(?:releases|remarks)[^"]+)"\s+class="collection-result__link"[^>]*>\s*(.+?)\s*</a>\s*'
    r'<div class="collection-result-meta"[^>]*>\s*<span[^>]*>([^<]*)</span>\s*<span[^>]*>([^<]+)</span>',
    re.S)


def collect_wh(max_pages=400):
    out, seen = [], set()
    for page in range(1, max_pages + 1):
        url = ("https://www.whitehouse.gov/briefings-statements/" if page == 1
               else f"https://www.whitehouse.gov/briefings-statements/page/{page}/")
        try:
            html = http_get(url)
        except FetchError as e:
            log(f"  wh listing page{page} 结束：{e}")
            break
        new = 0
        for m in WH_ITEM_RE.finditer(html):
            u, title = m.group(1), m.group(2).strip()
            if u in seen:
                continue
            seen.add(u)
            new += 1
            tm = re.search(r'datetime="(\d{4}-\d{2}-\d{2})', html[m.end():m.end() + 2000])
            out.append((tm.group(1) if tm else "", u, title))
        if new == 0:
            break
        if page % 20 == 0:
            log(f"  wh listing: {page} 页，{len(out)} 条")
        sleep_a_bit()
    return out


def collect_state(max_pages=400):
    out, seen = [], set()
    for page in range(1, max_pages + 1):
        url = ("https://www.state.gov/press-releases/" if page == 1
               else f"https://www.state.gov/press-releases/page/{page}/")
        try:
            html = http_get(url)
        except FetchError as e:
            log(f"  state listing page{page} 结束：{e}")
            break
        cards = STATE_CARD_RE.findall(html)
        if not cards:
            break
        new = 0
        for ctype, u, title, speaker, dstr in cards:
            if u in seen:
                continue
            seen.add(u)
            new += 1
            try:
                d = datetime.strptime(dstr.strip(), "%B %d, %Y").date().isoformat()
            except ValueError:
                continue
            out.append((d, u, f"[{ctype.strip()}] {re.sub(r'<[^>]+>', '', title).strip()} — {speaker.strip()}"))
        if new == 0:
            break
        if page % 20 == 0:
            log(f"  state listing: {page} 页，{len(out)} 条")
        sleep_a_bit()
    return out


def fetch_body(url, container_pat):
    try:
        html = http_get(url)
    except FetchError as e:
        log(f"  跳过 {url}: {e}")
        return None
    m = re.search(container_pat, html, re.S)
    body_html = m.group(1) if m else html
    paras = [strip_html(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", body_html, re.S)]
    return "\n\n".join(p for p in paras if len(p) > 60) or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("wh", "state"), required=True)
    ap.add_argument("--start")
    ap.add_argument("--end")
    args = ap.parse_args()

    items = collect_wh() if args.source == "wh" else collect_state()
    log(f"{args.source} 列表收集完成：{len(items)} 条")
    dates = sorted({d for d, _, _ in items if d})
    log(f"日期范围：{dates[0] if dates else '-'} .. {dates[-1] if dates else '-'}")

    from collections import defaultdict
    by_date = defaultdict(list)
    for d, u, t in items:
        if not d:
            continue
        if args.start and d < args.start:
            continue
        if args.end and d > args.end:
            continue
        by_date[d].append((u, t))

    container = (r'class="entry-content[^"]*"[^>]*>(.*?)(?:</main|<footer)'
                 if args.source == "state"
                 else r'class="entry-content[^"]*"[^>]*>(.*?)(?:</main|<footer)')
    written = 0
    for d in sorted(by_date):
        sections = []
        for u, t in by_date[d]:
            sleep_a_bit()
            text = fetch_body(u, container)
            if text:
                sections.append((t, text + f"\n\n> 原文：{u}"))
        if not sections:
            continue
        title = (f"White House Briefings & Statements · {d}" if args.source == "wh"
                 else f"U.S. Department of State Releases · {d}")
        if write_md(args.source if args.source == "state" else "whitehouse",
                    d, f"{d}.md", title, sections):
            written += 1
            if written % 10 == 0:
                log(f"  已写 {written} 天")
    log(f"{args.source} 回填完成：{written} 天")


if __name__ == "__main__":
    main()
