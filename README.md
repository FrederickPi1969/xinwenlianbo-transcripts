# 新闻联播每日文字稿 · Xinwen Lianbo Daily Transcripts

《新闻联播》每天 19:00（北京时间）播出，央视网会在网页端发布**编辑部人工整理**的逐条新闻文字稿。本项目用 GitHub Actions 每天自动抓取这些官方稿件，按 **年份 / 日期** 存成小文件，形成一份可长期积累、可程序化消费的公开数据集。

> 当前更新时间：<!-- UPDATED_AT -->2026-09-06 00:55 北京时间<!-- /UPDATED_AT -->

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
| 2026 | 248 | [news/2026/](news/2026/) |
| 2025 | 365 | [news/2025/](news/2025/) |
| 2024 | 366 | [news/2024/](news/2024/) |
| 2023 | 365 | [news/2023/](news/2023/) |
| 2022 | 365 | [news/2022/](news/2022/) |
| 2021 | 364 | [news/2021/](news/2021/) |
| 2020 | 366 | [news/2020/](news/2020/) |
| 2019 | 365 | [news/2019/](news/2019/) |
| 2018 | 365 | [news/2018/](news/2018/) |
| 2017 | 365 | [news/2017/](news/2017/) |
| 2016 | 366 | [news/2016/](news/2016/) |
| 2015 | 364 | [news/2015/](news/2015/) |
| 2014 | 365 | [news/2014/](news/2014/) |
| 2013 | 365 | [news/2013/](news/2013/) |
| 2012 | 366 | [news/2012/](news/2012/) |
| 2011 | 365 | [news/2011/](news/2011/) |
| 2010 | 364 | [news/2010/](news/2010/) |
| 2009 | 364 | [news/2009/](news/2009/) |
| 2008 | 366 | [news/2008/](news/2008/) |
| 2007 | 362 | [news/2007/](news/2007/) |
<!-- END:YEARS -->

## 最近更新

<!-- BEGIN:RECENT -->
- [2026-09-05](./news/2026/20260905.md) — 12 条
- [2026-09-04](./news/2026/20260904.md) — 18 条
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
<!-- END:RECENT -->

## 数据源

| 日期范围 | 来源 | 说明 |
| --- | --- | --- |
| 2016-03-30 → 今天 | [央视网](https://tv.cctv.com/lm/xwlb/) | 官方每日目录页 `tv.cctv.com/lm/xwlb/day/YYYYMMDD.shtml`，逐条进入详情页抽取 `#content_area` 官方文字稿与标题 |
| 2007 → 2016-03-29 | [cn.govopendata.com](https://cn.govopendata.com/xinwenlianbo/) | 央视网无此段每日目录页，采用第三方每日聚合页（其内容同样聚合自央视网页稿） |

两套来源互为兜底：任一来源抓取失败或解析结果异常时自动切换另一个。

## 全球新闻 Transcript 源（transcripts/）

按审计文档分层纳入**官方可直接下载**的源，统一存放于 `transcripts/<provider>/<YYYY>/`，每 provider 每年一份 `catalogue.json`。抓取器：`crawler/global_daily.py`（零依赖），定时：`.github/workflows/global-daily.yml`（每日 09:40/21:40 UTC，幂等回看 3 天）。

| Provider | 层级 | 入口模式 | 说明 |
| --- | --- | --- | --- |
| `cnn` | T1 | `transcripts.cnn.com/date/YYYY-MM-DD` → 逐 show 逐 segment | 官方逐字稿，含 speaker 标签与时间戳；每天一档节目一个文件；URL 可回溯至 2010+ |
| `democracy-now` | T2 | `democracynow.org/shows/Y/M/D` → 逐 story | 官方分段稿；过滤订阅推广段；archive 可回溯多年 |
| `pbs` | T2 | `pbs.org/newshour/show/<月名>-<D>-<Y>-...-full-episode` → 逐 segment "Read the Full Transcript" | 官方分段稿；机器+人工轻度编辑；周末无节目 |
| `whitehouse` | T1 | `whitehouse.gov/briefings-statements/`（列表 `<time datetime>` 定日期） | 官方 remarks/statements；无发布的日子为空 |
| `npr` | T2 | `feeds.npr.org/{1001,1002}` + 节目页 → `npr.org/transcripts/<storyId>` | 官方 story transcript（`has-transcript` 才有）；发现路径只覆盖最近几天，深历史需官方 API |
| `state` | T1 | `state.gov/press-releases/`（collection-result 卡片） | 官方 press statements/remarks；列表可翻至站点起点 |
| `aljazeera` | T3 | RSS `aljazeera.com/xml/rss/all.xml` → 静态文章 | 半岛电视台英文（中东视角全球新闻） |
| `euronews` | T3 | RSS → 静态文章 | 欧洲新闻台（泛欧洲覆盖） |
| `dw-en` | T3 | RSS `rss.dw.com/rdf/rss-en-all` → 静态文章 | DW 英文主新闻（德国视角） |
| `kbs` | T3 | `world.kbs.co.kr/service/news_list.htm`（静态站） | KBS WORLD Radio 英文新闻（配音频 written_news）；直连 |
| `un` | T1 | `press.un.org/en/<YYYY>/db<YYMMDD>.doc.htm`（双镜像） | UN 秘书长发言人午间简报 near-verbatim 全文；**经 Endeavor ULSCAR opencli 渲染**；历史 2022 前后起；仅 Cosmos 端运行 |
| `akashvani` | T1 | `newsonair.gov.in/bulletins-detail/<cat>-<N>/`（顺序 ID + 页面日期权威分桶） | 印度 AIR 英语公报（morning/midday/evening）；存档 2023-10 起；`--ak-full` 全量回填 |

**已裁撤（2026-09-04，价值/成本不匹配，connector 保留可随时重启）**：Yle Selkouutiset（易读芬兰语，~2KB/天）、Arirang 首页捕获（薄且不稳）、DW 慢速德语（语言学习节目，~5KB/天）。

**审计通过但暂未纳入（2026-09-04 直连 + proxy 双重复测）**：

| 源 | 实测证据 | 解锁方向 |
| --- | --- | --- |
| Reuters World News | 直连 **401**、proxy 出口仍 **401**（指纹级反爬，非 IP 级） | 授权 API |
| UN Noon Briefing | `dbYYMMDD.doc.htm` 规律已知，但直连/proxy 均返回 Client Challenge | 官方 RSS/API |
| RFI français facile | 直连/proxy 均 **403**（WAF 指纹） | 官方 RSS 文本 |
| Sveriges Radio lätt svenska | 直连/proxy 均 **403** | 同上 |
| DW slow news | 站点改版后为 JS 壳（列表/正文客户端渲染） | headless 或官方 API |
| CBC Front Burner | transcript 索引页可达，但 episode 页与 audio-api 均为 Next.js HTML 壳 | 逆向 listen 数据接口 |
| ABC Australia AM/TWD/PM | 平台迁移 abc.net.au/listen（JS），listen API 404 | 逆向 listen 数据接口 |
| NHK NEWS WEB EASY / Yle Selkouutiset / Arirang / VOA LE 每日区 | 首页为 JS 壳或文章列表客户端渲染，无静态链接 | headless/JSON API |
| FT / NYT The Daily | 付费墙（T1-L 定位） | 授权订阅会话 |

ABC/NBC/CBS 晚间新闻：按审计维持 Fallback 定位（Internet Archive 闭字幕 / Vanderbilt），不与官方 transcript 混层，未纳入本仓库。

**合规**：所有抓取路径均核对过 robots.txt（未被 Disallow）；各源保持低速率、带 UA、可识别抓取；内容权利归各机构，仓库仅作格式整理与存档，请勿用于再发布/训练等超出授权的用途（同上文数据说明）。


## 自动更新（新闻联播 · 双路保险）

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
python3 crawler/xwlb.py --today                # 新闻联播：抓今天
python3 crawler/xwlb.py --recent 7             # 新闻联播：补最近 7 天
python3 crawler/xwlb.py --start 20160330 --end 20161231 --workers 4
python3 crawler/xwlb.py --date 20070601 --source govopendata
python3 crawler/build_index.py                 # 重建 catalogue.json 与本 README

python3 crawler/global_daily.py --recent 3     # 全球源：CNN/DN!/PBS/WH
python3 crawler/global_daily.py --date 2026-09-02 --sources cnn,pbs
python3 crawler/global_daily.py --start 2026-08-20 --end 2026-09-01
python3 crawler/global_daily.py --reindex      # 重建 transcripts catalogue
```

遵守标准 `HTTPS_PROXY` 环境变量；对源站低速率、带抖动的礼貌抓取。

## 存储架构与 2GB 规则

**Cosmos（内网服务器，3.6T 盘）= 全量正本**：
- `~/xwlb/xinwenlianbo-transcripts`：GitHub 主仓克隆 + 全部回填 worker（tmux：新闻联播/DN/PBS/State/WH/NPR lane）
- `~/xwlb/cnn-archive`：**CNN 2010→今天全量**（GB 级，不上 GitHub），每周 git bundle 容灾到 `~/xwlb/backups/`
- cron：healer 每 2h（govopendata+代理备路）、global daily 双时段、CNN 每日增量、体积监控

**GitHub 主仓 ≤ 2GB 规则**：
- 非CNN源全量上仓（合计 ~400MB 量级，多年内无压力）
- CNN 在 GitHub 只保留**最近 400 天**（`global-daily.yml` 每次运行自动裁剪 HEAD；当前 ~150MB）
- 监控：Cosmos 每周记录 pack 体积，超 1.5GB 触发告警（`logs/SIZE_ALERT`）
- 超限 runbook：`git filter-repo --path transcripts/cnn/<旧年份> --invert-paths` 裁历史 → force-push → 各端重新 clone（GH Actions 自动恢复，Cosmos 从 cnn-archive 补窗口）

**已退役**：Mac 本机的 launchd healer 与回填 worker（2026-09-04 迁至 Cosmos；Mac 仓库目录留存为档案）。

## 数据说明与权利

- 文字稿权利归 [中央广播电视总台](https://tv.cctv.com/) 所有，本项目仅做格式整理与存档，请勿用于侵犯权利人权益的用途。
- 注意：这是**编辑部播报稿**，不是带时间戳的逐字 verbatim 转录（不含主持人串场口语等），适合语义分析、主题建模、NER、知识图谱、RAG 等场景。
- 本仓库代码以 MIT 许可发布（见 [LICENSE](LICENSE)）。
