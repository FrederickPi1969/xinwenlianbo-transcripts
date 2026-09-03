#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
看门狗：检查数据新鲜度，必要时调用爬虫自愈。

设计（双路保险）：
- 主路  daily.yml    ：GitHub Actions，CCTV 优先（runner 直连央视网畅通，
                        govopendata 的 Cloudflare 常拦数据中心 IP）
- 备路  本机 launchd ：govopendata 优先 + 代理池（对 Cloudflare 免疫），
                        同时推 origin 与私有镜像仓
- 哨兵  watchdog.yml ：GitHub Actions 独立 workflow 文件与时段，主路失效时
                        尝试补救，补救仍失败则开 Issue 告警（恢复后自动关闭）

用法：
    python3 watchdog.py --check                 # 只检查：健康 exit 0，过期 exit 3
    python3 watchdog.py --heal --prefer cctv    # 检查并自愈：健康/已治愈 exit 0，
                                                # 仍过期 exit 5（触发告警）
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS_DIR = os.path.join(BASE_DIR, "news")
CRAWLER = os.path.join(BASE_DIR, "crawler", "xwlb.py")
TZ = ZoneInfo("Asia/Shanghai")

# 节目 19:00 播出，页面当晚就绪；21 点后即应存在当天数据
READY_HOUR = 21
SWEEP_DAYS = 14          # 自愈回看窗口
EXIT_HEALTHY, EXIT_STALE, EXIT_STILL_STALE = 0, 3, 5


def expected_latest(now=None):
    """此刻理应存在的最新日期（北京时间）。"""
    now = now or datetime.now(TZ)
    today = now.date()
    return (today if now.hour >= READY_HOUR else today - timedelta(days=1))


def scan_latest():
    """仓库中实际存在的最新日期 YYYYMMDD；无数据返回 None。"""
    latest = None
    if not os.path.isdir(NEWS_DIR):
        return None
    for year in os.listdir(NEWS_DIR):
        ydir = os.path.join(NEWS_DIR, year)
        if not (re.fullmatch(r"(19|20)\d{2}", year) and os.path.isdir(ydir)):
            continue
        for fn in os.listdir(ydir):
            m = re.fullmatch(r"(\d{8})\.md", fn)
            if m and (latest is None or m.group(1) > latest):
                latest = m.group(1)
    return latest


def missing_days(expected, sweep=SWEEP_DAYS):
    """最近 sweep 天中，晚于 expected-sweep 且尚不存在的日期。"""
    start = (datetime.strptime(expected, "%Y%m%d") - timedelta(days=sweep - 1)).strftime("%Y%m%d")
    d0 = datetime.strptime(start, "%Y%m%d").date()
    d1 = datetime.strptime(expected, "%Y%m%d").date()
    gaps = []
    while d0 <= d1:
        ymd = d0.strftime("%Y%m%d")
        if not looks_present(ymd):
            gaps.append(ymd)
        d0 += timedelta(days=1)
    return gaps


def looks_present(yyyymmdd):
    path = os.path.join(NEWS_DIR, yyyymmdd[:4], f"{yyyymmdd}.md")
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return False
    return len(re.findall(r"^## \d+\. ", text, re.M)) >= 3 and len(text) > 1200


def status():
    expected = expected_latest().strftime("%Y%m%d")
    latest = scan_latest()
    gaps = missing_days(expected) if latest else ["<no data>"]
    return {
        "now_beijing": datetime.now(TZ).isoformat(timespec="seconds"),
        "expected_latest": expected,
        "actual_latest": latest,
        "missing_recent": gaps,
        "healthy": latest is not None and latest >= expected,
    }


def heal(prefer):
    """对缺口窗口执行爬虫（幂等），返回事后状态。"""
    st = status()
    if st["healthy"]:
        return st
    expected = st["expected_latest"]
    start = (datetime.strptime(expected, "%Y%m%d")
             - timedelta(days=SWEEP_DAYS - 1)).strftime("%Y%m%d")
    cmd = [sys.executable, CRAWLER, "--start", start, "--end", expected,
           "--source", "auto", "--prefer", prefer, "--workers", "3"]
    print("[watchdog] healing:", " ".join(cmd), flush=True)
    try:
        subprocess.run(cmd, check=False, timeout=45 * 60)
    except subprocess.TimeoutExpired:
        print("[watchdog] crawl timed out", flush=True)
    return status()


def main():
    ap = argparse.ArgumentParser(description="新闻联播数据看门狗")
    ap.add_argument("--check", action="store_true", help="只检查不修复")
    ap.add_argument("--heal", action="store_true", help="检查并自愈")
    ap.add_argument("--prefer", choices=("cctv", "govopendata"), default="cctv",
                    help="自愈时优先数据源")
    args = ap.parse_args()
    if not (args.check or args.heal):
        ap.error("需要 --check 或 --heal")

    st = status()
    if args.check or st["healthy"]:
        print(json.dumps(st, ensure_ascii=False, indent=2))
        sys.exit(EXIT_HEALTHY if st["healthy"] else EXIT_STALE)

    st = heal(args.prefer)
    print(json.dumps(st, ensure_ascii=False, indent=2))
    sys.exit(EXIT_HEALTHY if st["healthy"] else EXIT_STILL_STALE)


if __name__ == "__main__":
    main()
