# 新闻联播每日文字稿 · Xinwen Lianbo Daily Transcripts

《新闻联播》每天 19:00（北京时间）播出，央视网会在网页端发布**编辑部人工整理**的逐条新闻文字稿。本项目用 GitHub Actions 每天自动抓取这些官方稿件，按 **年份 / 日期** 存成小文件，形成一份可长期积累、可程序化消费的公开数据集。

> 当前更新时间：<!-- UPDATED_AT -->2026-09-04 06:16 北京时间<!-- /UPDATED_AT -->

## 数据布局

```text
news/
├── 2022/
│   ├── 20220924.md        ← 每天一个文件：标题 + 完整正文，按播出顺序
│   ├── 20220925.md
│   └── catalogue.json     ← 当年目录（date / file / source / 各条标题）
├── 2023/
└── ...
```

单日文件结构：

```markdown
# 新闻联播 2026-09-03
- 数据源：央视网（CCTV 官方文字稿）
- 目录页：https://tv.cctv.com/lm/xwlb/day/20260903.shtml
## 本期节目主要内容
## 1. 第一条新闻标题
正文……
> 原文：https://tv.cctv.com/.../VIDE....shtml
```

## 年份总表

<!-- BEGIN:YEARS -->
| 年份 | 天数 | 目录 |
| --- | ---: | --- |
| 2026 | 13 | [news/2026/](news/2026/) |
| 2020 | 5 | [news/2020/](news/2020/) |
| 2015 | 1 | [news/2015/](news/2015/) |
| 2012 | 154 | [news/2012/](news/2012/) |
| 2011 | 365 | [news/2011/](news/2011/) |
| 2010 | 364 | [news/2010/](news/2010/) |
| 2009 | 364 | [news/2009/](news/2009/) |
| 2008 | 366 | [news/2008/](news/2008/) |
| 2007 | 362 | [news/2007/](news/2007/) |
<!-- END:YEARS -->

## 最近更新

<!-- BEGIN:RECENT -->
- [2026-09-03](./news/2026/20260903.md) — 15 条
- [2026-09-02](./news/2026/20260902.md) — 12 条
- [2026-09-01](./news/2026/20260901.md) — 17 条
- [2026-08-31](./news/2026/20260831.md) — 14 条
- [2026-08-30](./news/2026/20260830.md) — 14 条
- [2026-08-29](./news/2026/20260829.md) — 12 条
- [2026-08-28](./news/2026/20260828.md) — 10 条
- [2026-08-27](./news/2026/20260827.md) — 16 条
- [2026-08-26](./news/2026/20260826.md) — 17 条
- [2026-08-25](./news/2026/20260825.md) — 15 条
- [2026-08-24](./news/2026/20260824.md) — 15 条
- [2026-08-23](./news/2026/20260823.md) — 13 条
- [2026-08-22](./news/2026/20260822.md) — 10 条
- [2020-01-05](./news/2020/20200105.md) — 15 条
<!-- END:RECENT -->

## 数据源

| 日期范围 | 来源 | 说明 |
| --- | --- | --- |
| 2016-03-30 → 今天 | [央视网](https://tv.cctv.com/lm/xwlb/) | 官方每日目录页 `tv.cctv.com/lm/xwlb/day/YYYYMMDD.shtml`，逐条进入详情页抽取 `#content_area` 官方文字稿与标题 |
| 2007 → 2016-03-29 | [cn.govopendata.com](https://cn.govopendata.com/xinwenlianbo/) | 央视网无此段每日目录页，采用第三方每日聚合页（其内容同样聚合自央视网页稿） |

两套来源互为兜底：任一来源抓取失败或解析结果异常时自动切换另一个。

## 自动更新（双路保险）

数据新鲜度由三层机制共同保证，任一路失效，其余路径可独立撑住：

| 层 | 载体 | 时段（北京） | 数据源偏好 | 失效场景兜底 |
| --- | --- | --- | --- | --- |
| **主路** `daily.yml` | GitHub Actions | 21:20 + 次日 00:20，抓最近 14 天缺口 | CCTV 优先（runner 直连央视网畅通） | 双时段 + 幂等回看，自愈 cron 延迟/跳过 |
| **哨兵** `watchdog.yml` | GitHub Actions（独立 workflow 文件/时段） | 22:35 + 次日 01:35 | CCTV 优先 | 主路 workflow 被改坏/被禁时接管；补救仍失败则**自动开 Issue 告警**（恢复后自动关闭） |
| **备路** 本机 launchd | Frederick 的 Mac，每 2 小时 | 随时（健康时零网络开销） | **govopendata 优先 + 代理池**（对 Cloudflare 免疫，与 runner 路径异构） | GitHub 全挂/两源互相被拦时仍可写入；同时推**私有镜像仓**防主仓意外 |

关键互补性：govopendata 的 Cloudflare 对数据中心 IP（GitHub runner）不友好，但对代理池出口畅通；CCTV 央视网则对两者都畅通。因此两路刻意使用不同的首选源与不同的网络出口，避免共享故障模式。

源级还有第二重冗余：爬虫对每一天都会在 CCTV 与 govopendata 之间自动切换（`--prefer` 可指定顺序），单日抓取失败先换源重试再报错。

- `.github/workflows/backfill.yml`：手动触发（`workflow_dispatch`），给定起止日期做历史回填。
- 状态检查：`python3 crawler/watchdog.py --check` 输出 JSON（`healthy` / `missing_recent`）。

## 爬虫

零第三方依赖，Python 3.9+ 标准库实现：

```bash
python3 crawler/xwlb.py --today                # 抓今天
python3 crawler/xwlb.py --recent 7             # 补最近 7 天
python3 crawler/xwlb.py --start 20160330 --end 20161231 --workers 4
python3 crawler/xwlb.py --date 20070601 --source govopendata
python3 crawler/build_index.py                 # 重建 catalogue.json 与本 README
```

遵守标准 `HTTPS_PROXY` 环境变量；对源站低速率、带抖动的礼貌抓取。

## 数据说明与权利

- 文字稿权利归 [中央广播电视总台](https://tv.cctv.com/) 所有，本项目仅做格式整理与存档，请勿用于侵犯权利人权益的用途。
- 注意：这是**编辑部播报稿**，不是带时间戳的逐字 verbatim 转录（不含主持人串场口语等），适合语义分析、主题建模、NER、知识图谱、RAG 等场景。
- 本仓库代码以 MIT 许可发布（见 [LICENSE](LICENSE)）。
