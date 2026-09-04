#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ULSCAR 渲染依赖源的每日抓取（只能在可达 Endeavor ULSCAR 服务的机器上运行，即 Cosmos）。

源：
- un       UN Daily Noon Briefing（near-verbatim 官方 transcript）
           URL 确定性：press.un.org/en/<YYYY>/db<YYMMDD>.doc.htm → ULSCAR opencli 渲染
- yle      Yle Selkouutiset（简明芬兰语新闻，当日首页即全文）
- arirang  Arirang News（jina 渲染首页含多篇完整报道）

用法：
    python3 rendered_daily.py --today
    python3 rendered_daily.py --recent 3
    python3 rendered_daily.py --date 2026-09-03
    python3 rendered_daily.py --start 2026-01-01 --end 2026-09-03 --sources un
输出：transcripts/<provider>/<YYYY>/<YYYY-MM-DD>.md
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from global_daily import write_md, day_total_chars  # noqa: E402
from xwlb import log  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ULSCAR = os.environ.get("ULSCAR_BASE_URL", "http://100.114.26.88:23355").rstrip("/")

MIN_CHARS = {"un": 3000, "yle": 800, "arirang": 1500}


# --------------------------------------------------------------------------- #
# ULSCAR 客户端
# --------------------------------------------------------------------------- #

def _request_json(method, url, payload=None, timeout=30):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def ulscar_fetch(urls, timeout=240):
    """提交 URL 列表给 ULSCAR，轮询取结果。返回 [result_dict]（已解包 .result 层）。"""
    submitted = _request_json("POST", f"{ULSCAR}/scrape", {
        "urls": urls, "use_text_extraction": True, "use_bypass_paywall": True,
        "use_wbm": True, "headless": True, "processes": min(len(urls), 6),
    })
    job_ids = submitted.get("job_ids", [])
    if not job_ids:
        raise RuntimeError(f"ULSCAR no job_ids: {submitted}")
    deadline = time.monotonic() + timeout
    final = {}
    while time.monotonic() < deadline:
        final = _request_json("POST", f"{ULSCAR}/results_batch", {"job_ids": job_ids})
        status = str(final.get("status", "")).lower()
        if status in {"complete", "completed", "success", "done"}:
            return [item.get("result") or item
                    for item in final.get("results", []) if isinstance(item, dict)]
        time.sleep(3)
    raise TimeoutError(f"ULSCAR timeout: {final.get('status', '?')}")


CHALLENGE_MARKERS = ("Just a moment", "Enable JavaScript", "Client Challenge",
                     "captcha-container", "cf-chl", "Access denied")


def _usable(text):
    if not text or len(text) < 200:
        return False
    head = text[:2000]
    return not any(m.lower() in head.lower() for m in CHALLENGE_MARKERS)


def ulscar_text(urls, attempts=3):
    """返回 [(url, text)]；对失败/挑战页自动整批重试（ULSCAR 多通路回退有随机性）。"""
    pending = list(urls)
    out = {u: "" for u in urls}
    for attempt in range(attempts):
        if not pending:
            break
        try:
            results = ulscar_fetch(pending)
        except (TimeoutError, RuntimeError) as e:
            log(f"  ulscar attempt {attempt} 失败：{e}")
            time.sleep(5)
            continue
        still = []
        for u, r in zip(pending, results):
            text = (r.get("text") or "") if isinstance(r, dict) else ""
            if isinstance(r, dict) and r.get("success") and _usable(text):
                out[u] = text
            else:
                still.append(u)
        pending = still
        if pending:
            log(f"  ulscar attempt {attempt}: {len(pending)} 个 URL 未取到，重试")
            time.sleep(4)
    return [(u, out[u]) for u in urls]


# --------------------------------------------------------------------------- #
# 文本清洗（ULSCAR 返回 markdown）
# --------------------------------------------------------------------------- #

def md_clean(text):
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)      # 链接 → 锚文本
    text = text.replace("\\*", "*").replace("\\[", "[").replace("\\]", "]")
    text = re.sub(r"^\\?\\?\*\\?\*?", "", text, flags=re.M)   # 残留转义
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------- #
# 1. UN Daily Noon Briefing
# --------------------------------------------------------------------------- #

def ingest_un(date):
    yy, ymd = date[2:4], date.replace("-", "")[2:]
    url = f"https://press.un.org/en/{date[:4]}/db{ymd}.doc.htm"
    try:
        got = ulscar_text([url])
    except (TimeoutError, RuntimeError) as e:
        log(f"  un {date} ULSCAR 失败：{e}")
        return []
    text = md_clean(got[0][1]) if got else ""
    if len(text) < MIN_CHARS["un"] or "Briefing" not in text:
        return []  # 当日无简报（周末/假日）或渲染失败
    # 去掉页尾主题标签列表
    text = re.sub(r"\n(Middle East|Israel|Lebanon|Nepal|Madagascar|Syria|State of Palestine"
                  r"|Humanitarian issues|Peacekeeping|[\w ]+)(\n[\w &-]+){10,}\s*$",
                  "", text)
    title = "UN Daily Press Briefing by the Office of the Spokesperson for the Secretary-General"
    tm = re.search(r"# (.+)", text)
    path = write_md("un", date, f"{date}.md", tm.group(1) if tm else f"{title} · {date}",
                    [("全文", text)],
                    extra=[f"官方页：{url}", "transcript_kind: official near-verbatim（ULSCAR opencli 渲染）"])
    if path:
        log(f"  un: {len(text)} chars -> {os.path.basename(path)}")
    return [path] if path else []


# --------------------------------------------------------------------------- #
# 2. Yle Selkouutiset（当日首页全文捕获）
# --------------------------------------------------------------------------- #

def ingest_yle(date):
    try:
        got = ulscar_text(["https://yle.fi/uutiset/osasto/selkouutiset/"])
    except (TimeoutError, RuntimeError) as e:
        log(f"  yle {date} ULSCAR 失败：{e}")
        return []
    text = md_clean(got[0][1]) if got else ""
    if len(text) < MIN_CHARS["yle"]:
        return []
    path = write_md("yle", date, f"{date}.md", f"Yle Selkouutiset · {date}",
                    [("当日简明新闻（首页捕获）", text)],
                    extra=["来源：https://yle.fi/uutiset/osasto/selkouutiset/",
                           "transcript_kind: paired_script（简明芬兰语，ULSCAR 渲染）"])
    if path:
        log(f"  yle: {len(text)} chars -> {os.path.basename(path)}")
    return [path] if path else []


# --------------------------------------------------------------------------- #
# 3. Arirang News（首页多篇文章）
# --------------------------------------------------------------------------- #

def ingest_arirang(date):
    try:
        got = ulscar_text(["https://www.arirang.com/news"])
    except (TimeoutError, RuntimeError) as e:
        log(f"  arirang {date} ULSCAR 失败：{e}")
        return []
    text = md_clean(got[0][1]) if got else ""
    if len(text) < MIN_CHARS["arirang"]:
        return []
    # jina 输出把多篇报道拼在一页，按明显的时间戳/标题行切段
    sections = []
    blocks = re.split(r"\n(?=\d{2}:\d{2} |[A-Z][^\n]{30,}$)", text)
    cur = "当日新闻汇总"
    buf = []
    for b in blocks:
        first = b.split("\n", 1)[0].strip()
        if 25 < len(first) < 120 and not first[0].isdigit() and first.endswith((".", "?", "!")) is False:
            if buf:
                sections.append((cur, "\n".join(buf).strip()))
            cur, buf = first[:100], [b]
        else:
            buf.append(b)
    if buf:
        sections.append((cur, "\n".join(buf).strip()))
    sections = [(h, t) for h, t in sections if len(t) > 200] or [("当日新闻汇总", text)]
    path = write_md("arirang", date, f"{date}.md", f"Arirang News · {date}", sections,
                    extra=["来源：https://www.arirang.com/news",
                           "transcript_kind: written_news（ULSCAR jina 渲染）"])
    if path:
        log(f"  arirang: {len(sections)} 段 -> {os.path.basename(path)}")
    return [path] if path else []


# --------------------------------------------------------------------------- #
# 编排
# --------------------------------------------------------------------------- #

SOURCES = {"un": ingest_un, "yle": ingest_yle, "arirang": ingest_arirang}


def daterange(start, end):
    d0 = datetime.strptime(start, "%Y-%m-%d").date()
    d1 = datetime.strptime(end, "%Y-%m-%d").date()
    while d0 <= d1:
        yield d0.isoformat()
        d0 += timedelta(days=1)


def main():
    ap = argparse.ArgumentParser(description="ULSCAR 渲染源每日抓取")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--today", action="store_true")
    g.add_argument("--recent", type=int, metavar="N")
    g.add_argument("--date")
    g.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--sources", default=",".join(SOURCES))
    args = ap.parse_args()

    chosen = [s for s in args.sources.split(",") if s in SOURCES]
    if not chosen:
        sys.exit(f"无有效 source；可选：{','.join(SOURCES)}")

    if args.today:
        days = [datetime.now().date().isoformat()]
    elif args.recent is not None:
        today = datetime.now().date()
        days = [(today - timedelta(days=i)).isoformat() for i in range(args.recent - 1, -1, -1)]
    elif args.date:
        days = [args.date]
    else:
        if not (args.start and args.end):
            sys.exit("--start 需要 --end")
        days = list(daterange(args.start, args.end))

    log(f"rendered: {len(days)} 天 × {len(chosen)} 源：{days[0]} .. {days[-1]}")
    ok, empty, failed = 0, 0, 0
    for day in days:
        for key in chosen:
            label = f"{key} {day}"
            # yle/arirang 只做当日捕获，历史日期跳过
            if key in ("yle", "arirang") and day != days[-1]:
                continue
            try:
                paths = SOURCES[key](day)
                if paths:
                    ok += 1
                else:
                    empty += 1
                    log(f"  {label}: 无内容/已存在")
            except Exception as e:
                failed += 1
                log(f"  {label} FAIL {type(e).__name__} {e}")
    log(f"rendered 完成：written={ok} empty={empty} failed={failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
