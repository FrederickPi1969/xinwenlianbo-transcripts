#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全球权威新闻 Transcript 每日抓取（零第三方依赖）。

纳入标准（对应审计文档分层）：
- cnn            T1  官方整期/分段稿  transcripts.cnn.com/date/YYYY-MM-DD
- democracy-now  T2  官方分段稿      democracynow.org/shows/Y/M/D
- pbs            T2  官方分段稿      pbs.org/newshour/show/... "Read the Full Transcript"
- whitehouse     T1  官方 remarks/statements  whitehouse.gov/briefings-statements/
- akashvani      T1  官方公报全文     newsonair.gov.in WordPress REST API

明确未纳入（详见 README）：Reuters(401 bot 拦截)、UN(press.un.org Client Challenge)、
NPR(transcript 客户端渲染)、CBC(JS 应用)、State.gov(未定位到现政府路径)、
ABC Australia(迁移 JS listen 平台)、FT/NYT(付费墙，需授权会话)。

用法：
    python3 global_daily.py --today
    python3 global_daily.py --recent 3
    python3 global_daily.py --date 2026-09-02
    python3 global_daily.py --start 2026-08-20 --end 2026-09-02 [--sources cnn,dn]
输出：transcripts/<provider>/<YYYY>/<YYYY-MM-DD>[__<show>].md + 各 provider 年度 catalogue.json
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xwlb import http_get, strip_html, FetchError, log, UA  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE_DIR, "transcripts")
TZ = ZoneInfo("UTC")

MIN_CHARS = {"cnn": 4000, "democracy-now": 2500, "pbs": 2500,
             "whitehouse": 600, "akashvani": 1200}


def sleep_a_bit():
    time.sleep(0.45 + (id(object()) % 100) / 250.0)  # ~0.45-0.85s 抖动


def slug(s):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:60] or "untitled"


# --------------------------------------------------------------------------- #
# 写出
# --------------------------------------------------------------------------- #

def md_header(provider, date, title, extra_lines):
    return [f"# {title}", "",
            f"- 数据源：{provider}",
            f"- 日期：{date}",
            f"- 抓取时间：{datetime.now(ZoneInfo('UTC')).isoformat(timespec='seconds')}"] + \
           [f"- {k}" for k in extra_lines] + [""]


def write_md(provider, date, filename, title, sections, extra=None, force=False):
    """sections: list[(heading, text)]；返回路径。"""
    year = date[:4]
    d = os.path.join(OUT_DIR, provider, year)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, filename)
    if not force and os.path.exists(path) and os.path.getsize(path) > 512:
        return None
    lines = md_header(provider, date, title, extra or [])
    for h, t in sections:
        lines += [f"## {h}", "", t.strip(), ""]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")
    os.replace(tmp, path)
    return path


def day_total_chars(sections):
    return sum(len(t) for _, t in sections)


# --------------------------------------------------------------------------- #
# 1. CNN Transcripts
# --------------------------------------------------------------------------- #

CNN_SEG_RE = re.compile(r'href="(/show/([\w-]+)/date/(\d{4}-\d{2}-\d{2})/segment/(\d+))"')


def ingest_cnn(date):
    base = "https://transcripts.cnn.com"
    idx_html = http_get(f"{base}/date/{date}")
    shows = {}  # show_code -> [segment numbers in order]
    for path, code, d, segno in CNN_SEG_RE.findall(idx_html):
        if d != date:
            continue
        shows.setdefault(code, [])
        if int(segno) not in shows[code]:
            shows[code].append(int(segno))

    written = []
    for code, segs in sorted(shows.items()):
        segs.sort()
        sections, show_name = [], code
        for segno in segs:
            sleep_a_bit()
            try:
                html = http_get(f"{base}/show/{code}/date/{date}/segment/{segno:02d}")
            except FetchError as e:
                log(f"  cnn {code} seg{segno} 跳过：{e}")
                continue
            m = re.search(r'<p class="cnnTransStoryHead">(.*?)</p>', html, re.S)
            sub = re.search(r'<p class="cnnTransSubHead">(.*?)</p>', html, re.S)
            show_name = strip_html(m.group(1)) if m else show_name
            seg_title = strip_html(sub.group(1)).split(". Aired")[0] if sub else f"Segment {segno}"
            paras = [strip_html(p) for p in re.findall(r'<p class="cnnBodyText">(.*?)</p>', html, re.S)]
            body = "\n\n".join(p for p in paras if p and not p.startswith("Aired ")
                               and "RUSH TRANSCRIPT" not in p)
            if body:
                sections.append((f"[{segno:02d}] {seg_title}", body))
        if not sections:
            continue
        path = write_md("cnn", date, f"{date}__{slug(show_name)}.md",
                        f"CNN {show_name} · {date}", sections,
                        extra=[f"官方 archive：https://transcripts.cnn.com/show/{code}/date/{date}"],
                        )
        if path:
            written.append(path)
            log(f"  cnn {code}: {len(sections)} segments -> {os.path.basename(path)}")
    if not written and not shows:
        raise FetchError(f"cnn {date}: date index has no shows")
    return written


# --------------------------------------------------------------------------- #
# 2. Democracy Now!
# --------------------------------------------------------------------------- #

DN_LINK_RE = re.compile(r'href="(/(\d{4})/(\d{1,2})/(\d{1,2})/([a-z0-9_-]+)/?)"')

DN_JUNK_PREFIXES = ("Sign up for Democracy Now",
                    "For more information about these services")


def dn_clean(paras):
    """去掉订阅推广与 related-stories 聚合块。"""
    out = []
    for p in paras:
        if p.startswith(DN_JUNK_PREFIXES):
            continue
        if len(p) > 1500 and re.search(r"Story\w{3} \d{1,2}, 2026", p):
            continue
        out.append(p)
    return out


def ingest_dn(date):
    y, m, d = date.split("-")
    show_html = http_get(f"https://www.democracynow.org/shows/{y}/{int(m)}/{int(d)}")
    if "story" not in show_html and "Headlines" not in show_html:
        raise FetchError(f"dn {date}: show page looks empty")

    links, seen = [], set()
    for path, ly, lm, ld, s in DN_LINK_RE.findall(show_html):
        if (ly, lm, ld) == (y, str(int(m)), str(int(d))) and s not in seen:
            seen.add(s)
            links.append(path)
    if not links:
        raise FetchError(f"dn {date}: no story links")

    sections = []
    for path in links:
        if path.rstrip("/").endswith("/stream"):
            continue  # 网页专属 stream 页，非播出内容
        sleep_a_bit()
        try:
            html = http_get(f"https://www.democracynow.org{path}")
        except FetchError as e:
            log(f"  dn {path} 跳过：{e}")
            continue
        tm = re.search(r"<title>(.*?)</title>", html, re.S)
        title = strip_html(tm.group(1)).replace(" | Democracy Now!", "").strip() if tm \
            else path.rsplit("/", 1)[-1].replace("_", " ")
        art = re.search(r"<article[^>]*>(.*?)</article>", html, re.S)
        body_html = art.group(1) if art else html
        paras = dn_clean([strip_html(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", body_html, re.S)])
        text = "\n\n".join(p for p in paras if len(p) > 60)
        if text:
            sections.append((title, text))
    if day_total_chars(sections) < MIN_CHARS["democracy-now"]:
        raise FetchError(f"dn {date}: too little text ({day_total_chars(sections)} chars)")
    path = write_md("democracy-now", date, f"{date}.md",
                    f"Democracy Now! · {date}", sections,
                    extra=[f"节目页：https://www.democracynow.org/shows/{y}/{int(m)}/{int(d)}"])
    if path:
        log(f"  dn: {len(sections)} stories -> {os.path.basename(path)}")
    return [path] if path else []


# --------------------------------------------------------------------------- #
# 3. PBS NewsHour
# --------------------------------------------------------------------------- #

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]


def pbs_episode_candidates(date):
    y, m, d = date.split("-")
    base = f"{MONTHS[int(m) - 1]}-{int(d)}-{y}"
    return [
        f"https://www.pbs.org/newshour/show/{base}-pbs-news-hour-full-episode",   # 新模板
        f"https://www.pbs.org/newshour/show/{base}-pbs-newshour-full-episode",   # 旧模板
        f"https://www.pbs.org/newshour/show/{base}-pbs-newshour",
    ]


def pbs_discover_episode(date):
    """确定性 URL（新旧两种 slug）→ 仅近 7 天才允许回退到 latest 页发现。"""
    for url in pbs_episode_candidates(date):
        try:
            return url, http_get(url)
        except FetchError:
            continue
    from datetime import date as _date
    today = datetime.now(ZoneInfo("UTC")).date()
    target = datetime.strptime(date, "%Y-%m-%d").date()
    if abs((today - target).days) <= 7:
        latest = http_get("https://www.pbs.org/newshour/latest")
        m = re.search(r'href="(https://www\.pbs\.org/newshour/show/[a-z0-9-]*full-episode[a-z0-9-]*)"', latest)
        if m:
            return m.group(1), http_get(m.group(1))
    raise FetchError(f"pbs {date}: episode url not found")


def ingest_pbs(date):
    url, ep_html = pbs_discover_episode(date)
    # 校验页面对应的播出日（episode 页含日期文本）
    y, m, d = date.split("-")
    if f"{MONTHS[int(m) - 1]} {int(d)}, {y}".lower() not in ep_html.lower():
        raise FetchError(f"pbs {date}: episode page is for another date")

    seg_links, seen = [], set()
    for u in re.findall(r'href="(https://www\.pbs\.org/newshour/show/([a-z0-9-]+))"', ep_html):
        if u[1] not in seen and "full-episode" not in u[1]:
            seen.add(u[1])
            seg_links.append(u[0])
    if not seg_links:
        raise FetchError(f"pbs {date}: no segment links")

    sections = []
    for i, u in enumerate(seg_links, 1):
        sleep_a_bit()
        try:
            html = http_get(u)
        except FetchError as e:
            log(f"  pbs seg{i} 跳过：{e}")
            continue
        tm = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
        title = strip_html(tm.group(1)) if tm else u.rsplit("/", 1)[-1]
        # "Read the Full Transcript" 锚点后的正文
        anchor = re.search(r'Read the Full Transcript', html)
        if not anchor:
            continue
        after = html[anchor.end():anchor.end() + 120000]
        paras = [strip_html(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", after, re.S)]
        text = "\n\n".join(p for p in paras if len(p) > 40
                           and not p.startswith("Notice:"))
        if text:
            sections.append((title, text))
    if day_total_chars(sections) < MIN_CHARS["pbs"]:
        raise FetchError(f"pbs {date}: too little text ({day_total_chars(sections)} chars)")
    path = write_md("pbs", date, f"{date}.md", f"PBS NewsHour · {date}", sections,
                    extra=[f"整期页：{url}"])
    if path:
        log(f"  pbs: {len(sections)} segments -> {os.path.basename(path)}")
    return [path] if path else []


# --------------------------------------------------------------------------- #
# 4. White House briefings / remarks / statements
# --------------------------------------------------------------------------- #

WH_ITEM_RE = re.compile(
    r'<a href="(https://www\.whitehouse\.gov/briefings-statements/\d{4}/\d{2}/[a-z0-9-]+)/?"[^>]*>([^<]{5,200})</a>')
WH_TIME_RE = re.compile(r'datetime="(\d{4}-\d{2}-\d{2})')


def ingest_whitehouse(date):
    """WH 的 URL 只含年月，日期取列表项的 <time datetime>。"""
    items = []  # (pubdate, url, title)
    seen = set()
    for page in range(1, 6):
        url = ("https://www.whitehouse.gov/briefings-statements/" if page == 1
               else f"https://www.whitehouse.gov/briefings-statements/page/{page}/")
        try:
            html = http_get(url)
        except FetchError as e:
            log(f"  wh listing page{page} 失败：{e}")
            break
        page_items = []
        for m in WH_ITEM_RE.finditer(html):
            u, title = m.group(1), m.group(2).strip()
            if u in seen:
                continue
            seen.add(u)
            tm = WH_TIME_RE.search(html, m.end())
            pubdate = tm.group(1) if tm else ""
            page_items.append((pubdate, u, title))
        items.extend(page_items)
        dates = [d for d, _, _ in page_items]
        if not dates:
            break
        # 列表倒序：当整页都早于目标日期时停止翻页
        if max(dates) < date:
            break
        sleep_a_bit()
    urls = [u for d, u, _ in items if d == date]
    if not urls:
        return []  # 当日无发布，正常情况

    sections = []
    for u in urls:
        sleep_a_bit()
        try:
            html = http_get(u)
        except FetchError as e:
            log(f"  wh 跳过 {u}: {e}")
            continue
        tm = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
        title = strip_html(tm.group(1)) if tm else u.rsplit("/", 1)[-1]
        m = re.search(r'class="entry-content[^"]*"[^>]*>(.*?)(?:</main|<footer)', html, re.S)
        body_html = m.group(1) if m else html
        paras = [strip_html(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", body_html, re.S)]
        text = "\n\n".join(p for p in paras if len(p) > 60)
        if text:
            sections.append((title, text + f"\n\n> 原文：{u}"))
    if not sections:
        return []
    path = write_md("whitehouse", date, f"{date}.md",
                    f"White House Briefings & Statements · {date}", sections,
                    extra=["栏目：https://www.whitehouse.gov/briefings-statements/"])
    if path:
        log(f"  wh: {len(sections)} items -> {os.path.basename(path)}")
    return [path] if path else []


def http_post_form(url, data, referer=None, timeout=30):
    """POST 表单（Akashvani admin-ajax 用）。遵循环境变量代理。"""
    body = urllib.parse.urlencode(data).encode()
    headers = {"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, data=body, headers=headers)
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode(resp.headers.get_content_charset() or "utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last_err = type(e).__name__
            time.sleep(1.5 + attempt)
    raise FetchError(f"POST {url} -> {last_err}")


# --------------------------------------------------------------------------- #
# 5. Akashvani National Bulletins（bulletins-detail/<cat>-<N>/ 顺序 ID，页内日期权威）
# --------------------------------------------------------------------------- #

AK_CATEGORIES = ("morning-news", "midday-news", "evening-news")
AK_ARCHIVE_URL = "https://newsonair.gov.in/bulletins-detail-archive/"
AK_NONCE_RE = re.compile(r"security: '([a-f0-9]+)'")
AK_LINK_RE = re.compile(r'href="(https://newsonair\.gov\.in/bulletins-detail/([a-z-]+)-(\d+)/)"')
AK_DATE_RE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s+(\d{4})")


def ak_nonce():
    page = http_get(AK_ARCHIVE_URL)
    m = AK_NONCE_RE.search(page)
    if not m:
        raise FetchError("akashvani: nonce not found")
    return m.group(1)


def ak_max_ids():
    """用 7 天 AJAX 查询发现各分类当前最大 ID（AJAX 日期过滤语义不可靠，仅作发现用）。"""
    nonce = ak_nonce()
    ids = {}
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    frm = (now - timedelta(days=10)).strftime("%Y-%m-%d")
    to = now.strftime("%Y-%m-%d")
    for cat in AK_CATEGORIES:
        time.sleep(0.4)
        frag = http_post_form(
            "https://newsonair.gov.in/wp-admin/admin-ajax.php",
            {"action": "filter_bulletins_details", "security": nonce,
             "category": cat, "date_from": frm, "date_to": to, "paged": 1},
            referer=AK_ARCHIVE_URL)
        for _, c, n in AK_LINK_RE.findall(frag):
            ids[c] = max(ids.get(c, 0), int(n))
    if not ids:
        raise FetchError("akashvani: max-id discovery failed")
    return ids


def ak_fetch_bulletin(cat, n):
    """抓单条公报，返回 (date_iso, title, text, url) 或 None。"""
    url = f"https://newsonair.gov.in/bulletins-detail/{cat}-{n}/"
    try:
        html = http_get(url)
    except FetchError:
        return None
    dm = AK_DATE_RE.search(html)
    if not dm:
        return None
    d_iso = datetime.strptime(f"{dm.group(1)} {dm.group(2)} {dm.group(3)}",
                              "%B %d %Y").date().isoformat()
    tm = re.search(r"<title>([^<]*)</title>", html)
    title = tm.group(1).replace(" | Akashvani News", "").strip() if tm else cat
    m = re.search(r'class="[^"]*(entry-content|single-content|post-content|detail-content)[^"]*"'
                  r"[^>]*>(.*?)(</article|<footer)", html, re.S)
    body_html = m.group(2) if m else html
    paras = [strip_html(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", body_html, re.S)]
    text = "\n\n".join(p for p in paras if len(p) > 60)
    if not text:
        return None
    return d_iso, title, text, url


def ak_write_day(buckets, date):
    sections = []
    for cat in AK_CATEGORIES:
        for (d_iso, title, text, url) in sorted(buckets.get(cat, [])):
            if d_iso == date:
                sections.append((title, text + f"\n\n> 原文：{url}"))
    if not sections or day_total_chars(sections) < MIN_CHARS["akashvani"]:
        return None
    return write_md("akashvani", date, f"{date}.md",
                    f"Akashvani National Bulletins · {date}", sections,
                    extra=["来源：https://newsonair.gov.in/bulletins-detail-archive/",
                           "分类：morning/midday/evening-news（英语公报）",
                           "方法：顺序 ID 直爬，公报日期以页面为准"])


def ingest_akashvani(date, window=25):
    """日常模式：扫各分类 [max-window, max+2] 的 ID 窗口，按页内日期分桶。"""
    maxids = ak_max_ids()
    log(f"  ak max ids: {maxids}")
    buckets = {}
    for cat, mx in maxids.items():
        for n in range(max(1, mx - window), mx + 3):
            time.sleep(0.35)
            got = ak_fetch_bulletin(cat, n)
            if got:
                buckets.setdefault(cat, []).append(got)
    path = ak_write_day(buckets, date)
    if path:
        log(f"  akashvani: {date} -> {os.path.basename(path)}")
    return [path] if path else []


def ak_backfill_full():
    """全量回填：各分类从 ID 1 走到当前 max。幂等（已存在日期跳过写入）。"""
    maxids = ak_max_ids()
    log(f"  ak full walk max ids: {maxids}")
    buckets = {}
    for cat, mx in maxids.items():
        for n in range(1, mx + 1):
            time.sleep(0.3)
            got = ak_fetch_bulletin(cat, n)
            if got:
                buckets.setdefault(cat, []).append(got)
            if n % 100 == 0:
                log(f"  ak {cat}: {n}/{mx}")
    dates = {d for lst in buckets.values() for (d, *_ ) in lst}
    written = 0
    for d in sorted(dates):
        if ak_write_day(buckets, d):
            written += 1
    log(f"  ak full: {len(dates)} 天，新写 {written} 天")


# --------------------------------------------------------------------------- #
# 6. NPR Morning Edition + All Things Considered
# --------------------------------------------------------------------------- #

NPR_FEEDS = ("1001", "1002")  # Morning Edition, All Things Considered
NPR_ET = ZoneInfo("America/New_York")
NPR_STORY_URL_RE = re.compile(r"https://www\.npr\.org/\d{4}/\d{2}/\d{2}/([\w-]+)/[\w-]+")
NPR_COPYRIGHT_MARK = ("Copyright", "Accuracy and availability")


def npr_transcript_text(html):
    """NPR transcript 页正文：storytext 容器，段落以 <p> 分隔（无闭合）。"""
    m = re.search(r'class="[^"]*storytext[^"]*"[^>]*>(.*?)(?:</section>|<footer)', html, re.S)
    if not m:
        return None
    body = m.group(1)
    for mark in NPR_COPYRIGHT_MARK:
        i = body.find(mark)
        if i > 0:
            body = body[:i]
    body = re.sub(r"(?i)<br\s*/?>", "\n", body)
    body = body.replace("<p>", "\n").replace("<P>", "\n")
    text = strip_html(body)
    lines = [ln.strip() for ln in text.splitlines()
             if ln.strip() and ln.strip() not in ("Transcript", "transcript")]
    return "\n\n".join(lines) or None


def npr_candidate_stories():
    """候选 story：RSS（最近 ~1 天）+ 两档节目页（最近 ~3-5 天），URL 自带日期。"""
    cands = {}  # story_id -> (url, title)
    urls = []
    try:
        for feed_id in NPR_FEEDS:
            xml = http_get(f"https://feeds.npr.org/{feed_id}/rss.xml")
            urls += [m.group(1) for m in re.finditer(r"<link>([^<]+npr\.org/20[^<]+)</link>", xml)]
            sleep_a_bit()
    except FetchError as e:
        log(f"  npr feed 失败：{e}")
    for prog in ("morning-edition", "all-things-considered"):
        try:
            html = http_get(f"https://www.npr.org/programs/{prog}/")
            urls += re.findall(r'href="(https://www\.npr\.org/20\d\d/\d\d/\d\d/[\w-]+/[\w-]+)"', html)
            sleep_a_bit()
        except FetchError as e:
            log(f"  npr program {prog} 失败：{e}")
    for u in urls:
        m = NPR_STORY_URL_RE.match(u)
        if m:
            cands[m.group(1)] = u
    return cands


def ingest_npr(date):
    sections = []
    for story_id, u in npr_candidate_stories().items():
        # URL 里的日期必须等于目标日期
        dm = re.match(r"https://www\.npr\.org/(\d{4}/\d{2}/\d{2})/", u)
        if not dm or dm.group(1).replace("/", "-") != date:
            continue
        sleep_a_bit()
        try:
            html = http_get(f"https://www.npr.org/transcripts/{story_id}")
        except FetchError:
            continue  # 该 story 无 transcript，正常
        text = npr_transcript_text(html)
        tm = re.search(r"<title>(.*?)</title>", html, re.S)
        title = strip_html(tm.group(1)).replace(" : NPR", "").strip() if tm else story_id
        if text and len(text) > 500:
            sections.append((title,
                             text + f"\n\n> Story：{u}\n> Transcript：https://www.npr.org/transcripts/{story_id}"))
    if not sections:
        return []
    path = write_md("npr", date, f"{date}.md",
                    f"NPR Morning Edition + All Things Considered · {date}",
                    sections,
                    extra=["来源：feeds.npr.org/1001,1002 → npr.org/transcripts/<storyId>",
                           "注意：并非每个 segment 都有 transcript（官方行为），此处仅收录有稿条目"])
    if path:
        log(f"  npr: {len(sections)} stories -> {os.path.basename(path)}")
    return [path] if path else []


# --------------------------------------------------------------------------- #
# 7. U.S. Department of State（press releases / remarks / briefings）
# --------------------------------------------------------------------------- #

STATE_CARD_RE = re.compile(
    r'<p class="collection-result__date">([^<]+)</p>\s*'
    r'<a href="(https://www\.state\.gov/(?:releases|remarks)[^"]+)"\s+class="collection-result__link"[^>]*>\s*(.+?)\s*</a>\s*'
    r'<div class="collection-result-meta"[^>]*>\s*<span[^>]*>([^<]*)</span>\s*<span[^>]*>([^<]+)</span>',
    re.S)


def state_listing(max_pages=300):
    """翻完 /press-releases/ 列表，返回 [(date, type, url, title, speaker)]，倒序。"""
    out, seen = [], set()
    for page in range(1, max_pages + 1):
        url = ("https://www.state.gov/press-releases/" if page == 1
               else f"https://www.state.gov/press-releases/page/{page}/")
        try:
            html = http_get(url)
        except FetchError as e:
            log(f"  state listing page{page} 失败：{e}")
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
            out.append((d, ctype.strip(), u, re.sub(r"\s+", " ", title).strip(), speaker.strip()))
        if new == 0:
            break
        if page % 25 == 0:
            log(f"  state listing: {page} 页，{len(out)} 条")
            sleep_a_bit()
    return out


def ingest_state(date):
    cards = [c for c in state_listing(max_pages=12) if c[0] == date]
    if not cards:
        return []
    sections = []
    for d, ctype, u, title, speaker in cards:
        sleep_a_bit()
        try:
            html = http_get(u)
        except FetchError as e:
            log(f"  state 跳过 {u}: {e}")
            continue
        m = re.search(r'class="entry-content[^"]*"[^>]*>(.*?)(?:</main|<footer)', html, re.S)
        body_html = m.group(1) if m else ""
        paras = [strip_html(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", body_html, re.S)]
        text = "\n\n".join(p for p in paras if len(p) > 60)
        if text:
            sections.append((f"[{ctype}] {title} — {speaker}",
                             text + f"\n\n> 原文：{u}"))
    if not sections:
        return []
    path = write_md("state", date, f"{date}.md",
                    f"U.S. Department of State Releases · {date}", sections,
                    extra=["栏目：https://www.state.gov/press-releases/"])
    if path:
        log(f"  state: {len(sections)} items -> {os.path.basename(path)}")
    return [path] if path else []


# --------------------------------------------------------------------------- #
# 编排
# --------------------------------------------------------------------------- #

SOURCES = {
    "cnn": ingest_cnn,
    "dn": ingest_dn,
    "pbs": ingest_pbs,
    "wh": ingest_whitehouse,
    "npr": ingest_npr,
    "state": ingest_state,
    "ak": ingest_akashvani,
}


def reindex():
    """扫描 transcripts/，重建每个 provider 每年的 catalogue.json。"""
    if not os.path.isdir(OUT_DIR):
        return
    for provider in sorted(os.listdir(OUT_DIR)):
        pdir = os.path.join(OUT_DIR, provider)
        if not os.path.isdir(pdir):
            continue
        for year in sorted(os.listdir(pdir)):
            ydir = os.path.join(pdir, year)
            if not (os.path.isdir(ydir) and re.fullmatch(r"(19|20)\d{2}", year)):
                continue
            entries = []
            for fn in sorted(os.listdir(ydir)):
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}.*\.md", fn):
                    continue
                text = open(os.path.join(ydir, fn), encoding="utf-8").read()
                headings = re.findall(r"^## (.+)$", text, re.M)
                entries.append({"file": f"transcripts/{provider}/{year}/{fn}",
                                "size": len(text), "sections": len(headings),
                                "titles": headings[:40]})
            entries.sort(key=lambda e: e["file"], reverse=True)
            with open(os.path.join(ydir, "catalogue.json"), "w", encoding="utf-8") as fh:
                json.dump(entries, fh, ensure_ascii=False, indent=1)
            log(f"  index {provider}/{year}: {len(entries)} files")


def daterange(start, end):
    d0 = datetime.strptime(start, "%Y-%m-%d").date()
    d1 = datetime.strptime(end, "%Y-%m-%d").date()
    while d0 <= d1:
        yield d0.isoformat()
        d0 += timedelta(days=1)


def main():
    ap = argparse.ArgumentParser(description="全球新闻 transcript 每日抓取")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--today", action="store_true")
    g.add_argument("--recent", type=int, metavar="N")
    g.add_argument("--date")
    g.add_argument("--start")
    g.add_argument("--ak-full", action="store_true",
                   help="Akashvani 全量回填（按 ID 序列走完各分类）")
    ap.add_argument("--end")
    ap.add_argument("--sources", default=",".join(SOURCES),
                    help=f"逗号分隔：{','.join(SOURCES)}（默认全部）")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--reindex", action="store_true", help="只重建 catalogue.json")
    args = ap.parse_args()

    if args.reindex:
        reindex()
        return 0

    if args.ak_full:
        ak_backfill_full()
        reindex()
        return 0

    global write_force
    chosen = [s for s in args.sources.split(",") if s in SOURCES]
    if not chosen:
        sys.exit(f"无有效 source；可选：{','.join(SOURCES)}")

    if args.today:
        days = [datetime.now(ZoneInfo("UTC")).date().isoformat()]
    elif args.recent is not None:
        today = datetime.now(ZoneInfo("UTC")).date()
        days = [(today - timedelta(days=i)).isoformat() for i in range(args.recent - 1, -1, -1)]
    elif args.date:
        days = [args.date]
    else:
        if not (args.start and args.end):
            sys.exit("--start 需要 --end")
        days = list(daterange(args.start, args.end))

    log(f"global: {len(days)} 天 × {len(chosen)} 源：{days[0]} .. {days[-1]}")
    WEEKDAY_ONLY = {"dn", "pbs"}  # 周末不播出
    ok, empty, failed = 0, 0, 0
    for day in days:
        for key in chosen:
            label = f"{key} {day}"
            if key in WEEKDAY_ONLY and datetime.strptime(day, "%Y-%m-%d").weekday() >= 5:
                continue  # 周末无节目，正常
            try:
                paths = SOURCES[key](day)
                if paths:
                    ok += 1
                else:
                    empty += 1
                    log(f"  {label}: 无内容（正常缺失或已存在跳过）")
            except FetchError as e:
                failed += 1
                log(f"  {label} FAIL {e}")
    log(f"global 完成：written={ok} empty/skipped={empty} failed={failed}")
    reindex()
    if failed and failed == len(days) * len(chosen):
        sys.exit(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
