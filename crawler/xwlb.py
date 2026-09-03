#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
《新闻联播》每日文字稿爬虫（零第三方依赖，Python 3.9+ 标准库实现）。

数据源
------
1. cctv        央视网官方每日目录页 https://tv.cctv.com/lm/xwlb/day/YYYYMMDD.shtml
               （2016-03-30 起有效；目录页按播出顺序列出各条新闻，逐条抓取
                 详情页 #content_area 的官方文字稿）
2. govopendata 第三方聚合页 https://cn.govopendata.com/xinwenlianbo/YYYYMMDD/
               （2007 年起有效，作为更早历史与 CCTV 失败时的兜底）

用法
----
    python3 xwlb.py --today                     # 抓今天（北京时间）
    python3 xwlb.py --recent 7                  # 抓最近 7 天（已存在的自动跳过）
    python3 xwlb.py --date 20260903             # 抓指定一天
    python3 xwlb.py --start 20160330 --end 20161231 --workers 4
    python3 xwlb.py --date 20070601 --source govopendata

输出：news/YYYY/YYYYMMDD.md

代理：直接识别标准环境变量 HTTPS_PROXY / HTTP_PROXY（urllib 默认行为），
长跑时可在 shell 层轮换。对源站保持低速率、带抖动的礼貌抓取。
"""

import argparse
import concurrent.futures
import html as html_lib
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS_DIR = os.path.join(BASE_DIR, "news")
TZ = ZoneInfo("Asia/Shanghai")

CCTV_DAY_URL = "https://tv.cctv.com/lm/xwlb/day/{date}.shtml"
GOVOPEN_DAY_URL = "https://cn.govopendata.com/xinwenlianbo/{date}/"
CCTV_EARLIEST = "20160330"  # 央视网 day 页面最早可用日期

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

STORY_LINK_RE = re.compile(r"https?://tv\.cctv\.com/\d{4}/\d{2}/\d{2}/VIDE\w+\.shtml")
TITLE_TIT_RE = re.compile(r'class="tit"[^>]*>(.*?)</(?:div|h\d)>', re.S)
CONTENT_AREA_RE = re.compile(r'id="content_area"[^>]*>(.*?)</div>', re.S)
ABSTRACT_RE = re.compile(r'nrjianjie_shadow.*?<p[^>]*>(.*?)</p>', re.S)

_print_lock = threading.Lock()
_rate_lock = threading.Lock()
_rate_last = {}


def log(msg):
    with _print_lock:
        print(f"[{datetime.now(TZ).strftime('%H:%M:%S')}] {msg}", flush=True)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

def http_get(url, timeout=30, attempts=3):
    """GET 文本，带重试与指数退避。遵循环境变量代理设置。"""
    last_err = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                return data.decode(charset, "replace")
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                last_err = f"HTTP {e.code}"
            elif e.code == 404:
                raise DayNotFound(url)
            else:
                last_err = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last_err = type(e).__name__
        if attempt < attempts:
            time.sleep((2 ** attempt) * 0.7 + random.uniform(0, 1.2))
    raise FetchError(f"{url} -> {last_err}")


class FetchError(Exception):
    pass


class DayNotFound(FetchError):
    pass


def polite_sleep(source, workers=1):
    """每个数据源独立限速：单 worker 时给足间隔，多 worker 时适当放宽。"""
    base = 0.55 if source == "cctv" else 0.85
    if workers > 1:
        base = 0.15 if source == "cctv" else 0.35
    time.sleep(base + random.uniform(0.05, 0.55))


# --------------------------------------------------------------------------- #
# 文本规范化
# --------------------------------------------------------------------------- #

def strip_html(fragment):
    fragment = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
    text = re.sub(r"<[^>]+>", "", fragment)
    text = html_lib.unescape(text)
    lines = [re.sub(r"[ \t\u3000]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


# --------------------------------------------------------------------------- #
# 数据源：CCTV
# --------------------------------------------------------------------------- #

def cctv_story_links(day_html):
    links, seen = [], set()
    for url in STORY_LINK_RE.findall(day_html):
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def crawl_cctv(yyyymmdd):
    """返回 {abstract, items:[{title, content, url}], source:'cctv'}"""
    day_html = http_get(CCTV_DAY_URL.format(date=yyyymmdd))
    links = cctv_story_links(day_html)
    if len(links) < 2:
        raise FetchError("CCTV day page has no story links")

    abstract, items = "", []
    for url in links:
        try:
            page = http_get(url)
        except DayNotFound:
            continue
        m = TITLE_TIT_RE.search(page)
        raw_title = strip_html(m.group(1)) if m else ""
        is_episode = bool(re.match(r"^《新闻联播》", raw_title))
        if is_episode and not abstract:
            am = ABSTRACT_RE.search(page)
            if am:
                abstract = strip_html(am.group(1))
            polite_sleep("cctv")
            continue
        content_m = CONTENT_AREA_RE.search(page)
        content = strip_html(content_m.group(1)) if content_m else ""
        title = re.sub(r"^\s*\[视频\]\s*", "", raw_title).strip()
        if title and content:
            items.append({"title": title, "content": content, "url": url})
        polite_sleep("cctv")

    if len(items) < 3 or sum(len(i["content"]) for i in items) < 400:
        raise FetchError(f"CCTV parse suspicious: {len(items)} stories")
    return {"abstract": abstract, "items": items, "source": "cctv"}


# --------------------------------------------------------------------------- #
# 数据源：cn.govopendata.com
# --------------------------------------------------------------------------- #

class GovopenParser(HTMLParser):
    """解析每日聚合页：article.content-section > h2 + (div.content-body > p...)"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []
        self._cur = None
        self._capture = None      # 'title' | 'para'
        self._buf = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "")
        if tag in ("script", "style"):
            self._skip_depth += 1
            return
        if tag == "article" and "content-section" in classes.split():
            self._cur = {"title": "", "paras": []}
        elif self._cur is not None:
            if tag == "h2":
                self._capture, self._buf = "title", []
            elif tag == "p":
                self._capture, self._buf = "para", []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._cur is None:
            return
        if tag == "h2" and self._capture == "title":
            self._cur["title"] = re.sub(r"[ \t\u3000]+", " ", "".join(self._buf)).strip()
            self._capture = None
        elif tag == "p" and self._capture == "para":
            text = "".join(self._buf)
            text = re.sub(r"[ \t\u3000]+", " ", text).strip()
            if text:
                self._cur["paras"].append(text)
            self._capture = None
        elif tag == "article" and self._cur is not None:
            if self._cur["title"] or self._cur["paras"]:
                self.items.append(self._cur)
            self._cur = None

    def handle_data(self, data):
        if self._skip_depth or self._capture is None:
            return
        self._buf.append(data)


def crawl_govopendata(yyyymmdd):
    iso = f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
    page = http_get(GOVOPEN_DAY_URL.format(date=yyyymmdd))
    if "content-section" not in page:
        raise FetchError("govopendata page lacks content-section")
    parser = GovopenParser()
    parser.feed(page)
    items = []
    for sec in parser.items:
        title, content = sec["title"], "\n".join(sec["paras"])
        if title and len(content) > 30:
            items.append({"title": title, "content": content, "url": ""})
    if len(items) < 3 or sum(len(i["content"]) for i in items) < 400:
        raise FetchError(f"govopendata parse suspicious: {len(items)} sections")
    return {"abstract": "", "items": items, "source": "govopendata",
            "page": GOVOPEN_DAY_URL.format(date=yyyymmdd), "iso": iso}


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #

def render_markdown(yyyymmdd, payload):
    iso = f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
    src = payload["source"]
    lines = [f"# 新闻联播 {iso}", ""]
    if src == "cctv":
        day_url = CCTV_DAY_URL.format(date=yyyymmdd)
        lines += [f"- 数据源：央视网（CCTV 官方文字稿）",
                  f"- 目录页：{day_url}"]
    else:
        lines += [f"- 数据源：cn.govopendata.com 每日聚合页",
                  f"- 聚合页：{payload['page']}",
                  f"- 说明：早于 2016-03-30 的日期央视网无每日目录页，此稿来自第三方聚合"]
    lines += [f"- 新闻条数：{len(payload['items'])}",
              f"- 抓取时间：{datetime.now(TZ).isoformat(timespec='seconds')}",
              ""]

    if payload.get("abstract"):
        lines += ["## 本期节目主要内容", "", payload["abstract"], ""]

    for idx, item in enumerate(payload["items"], 1):
        lines += [f"## {idx}. {item['title']}", "", item["content"], ""]
        if item.get("url"):
            lines += [f"> 原文：{item['url']}", ""]
    return "\n".join(lines).rstrip() + "\n"


def output_path(yyyymmdd):
    return os.path.join(NEWS_DIR, yyyymmdd[:4], f"{yyyymmdd}.md")


def looks_complete(path):
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return False
    return len(re.findall(r"^## \d+\. ", text, re.M)) >= 3 and len(text) > 1200


# --------------------------------------------------------------------------- #
# 单日编排
# --------------------------------------------------------------------------- #

def crawl_one_day(yyyymmdd, source="auto", force=False, workers=1):
    """成功返回 'fetched'|'skipped'；失败抛异常。"""
    path = output_path(yyyymmdd)
    if not force and looks_complete(path):
        return "skipped"

    order = []
    if source in ("auto", "cctv") and yyyymmdd >= CCTV_EARLIEST:
        order.append("cctv")
    if source in ("auto", "govopendata"):
        order.append("govopendata")
    if not order:
        raise FetchError(f"{yyyymmdd} 早于央视网可用范围且未选择 govopendata")

    errors = []
    for src in order:
        try:
            payload = crawl_cctv(yyyymmdd) if src == "cctv" else crawl_govopendata(yyyymmdd)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(render_markdown(yyyymmdd, payload))
            os.replace(tmp, path)
            log(f"{yyyymmdd} OK ({src}, {len(payload['items'])} 条) -> {os.path.relpath(path, BASE_DIR)}")
            return "fetched"
        except FetchError as e:
            errors.append(f"{src}: {e}")
            if src == "cctv":
                polite_sleep("govopendata", workers)
    raise FetchError(f"{yyyymmdd} 失败 [{'; '.join(errors)}]")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def daterange(start, end):
    d0 = datetime.strptime(start, "%Y%m%d").date()
    d1 = datetime.strptime(end, "%Y%m%d").date()
    if d0 > d1:
        d0, d1 = d1, d0
    while d0 <= d1:
        yield d0.strftime("%Y%m%d")
        d0 += timedelta(days=1)


GOVOPEN_DAY_LINK_RE = re.compile(r'href="/xinwenlianbo/(\d{8})/"')


def discover_from_index(start, end):
    """从 govopendata 月份索引页收集范围内真实存在的日期（升序）。"""
    d0 = datetime.strptime(start, "%Y%m%d").date()
    d1 = datetime.strptime(end, "%Y%m%d").date()
    months = []
    cur = d0.replace(day=1)
    while cur <= d1:
        months.append(cur.strftime("%Y%m"))
        cur = (cur + timedelta(days=32)).replace(day=1)
    found = set()
    for ym in months:
        url = f"https://cn.govopendata.com/xinwenlianbo/{ym[:4]}/{ym[4:]}/"
        for attempt in range(3):
            try:
                html = http_get(url)
                found.update(int(d) for d in GOVOPEN_DAY_LINK_RE.findall(html)
                             if start <= d <= end)
                log(f"index {ym}: {len(found)} 天（累计）")
                break
            except FetchError as e:
                if attempt == 2:
                    log(f"index {ym} 获取失败：{e}")
                else:
                    time.sleep(3 + random.uniform(0, 3))
    return [f"{d:08d}" for d in sorted(found)]


def parse_args():
    p = argparse.ArgumentParser(description="新闻联播每日文字稿爬虫")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--today", action="store_true", help="抓今天（北京时间）")
    g.add_argument("--recent", type=int, metavar="N", help="抓最近 N 天（含今天）")
    g.add_argument("--date", help="抓指定日期 YYYYMMDD")
    g.add_argument("--start", help="范围起始 YYYYMMDD（配合 --end）")
    p.add_argument("--end", help="范围结束 YYYYMMDD")
    p.add_argument("--from-index", action="store_true",
                   help="范围模式下先读 govopendata 月份索引，只抓真实存在的日期")
    p.add_argument("--source", choices=("auto", "cctv", "govopendata"), default="auto")
    p.add_argument("--workers", type=int, default=1, help="按天并行度（默认 1）")
    p.add_argument("--force", action="store_true", help="已存在也重新抓取")
    return p.parse_args()


def main():
    args = parse_args()

    if args.today:
        days = [datetime.now(TZ).strftime("%Y%m%d")]
    elif args.recent is not None:
        today = datetime.now(TZ).date()
        days = [(today - timedelta(days=i)).strftime("%Y%m%d")
                for i in range(args.recent - 1, -1, -1)]
    elif args.date:
        days = [args.date]
    else:
        if not (args.start and args.end):
            sys.exit("--start 需要 --end")
        days = list(daterange(args.start, args.end))
        if args.from_index:
            discovered = discover_from_index(args.start, args.end)
            before = len(days)
            days = [d for d in days if d in set(discovered)]
            log(f"索引发现 {len(discovered)} 天（请求 {before} 天，过滤掉 {before - len(days)} 个不存在日期）")

    log(f"待处理 {len(days)} 天：{days[0]} .. {days[-1]}（source={args.source}, workers={args.workers}）")
    fetched, skipped, failed = [], [], []

    def work(day):
        try:
            return day, crawl_one_day(day, args.source, args.force, args.workers), None
        except FetchError as e:
            return day, "failed", str(e)

    if args.workers <= 1 or len(days) == 1:
        for day in days:
            d, status, err = work(day)
            (fetched if status == "fetched" else skipped if status == "skipped" else failed).append(d)
            if status == "failed":
                log(f"{d} FAIL {err}")
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for d, status, err in pool.map(work, days):
                (fetched if status == "fetched" else skipped if status == "skipped" else failed).append(d)
                if status == "failed":
                    log(f"{d} FAIL {err}")

    log(f"完成：fetched={len(fetched)} skipped={len(skipped)} failed={len(failed)}")
    if failed:
        with open(os.path.join(BASE_DIR, "failures.log"), "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now(TZ).isoformat(timespec='seconds')}\n")
            for d in failed:
                fh.write(d + "\n")
        if len(failed) == len(days):
            sys.exit(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
