# -*- coding: utf-8 -*-
"""内容源适配层。

每个源是一个薄适配器：拉取 -> 归一化成统一的候选结构。
业务层只看到 [{title, url, source, summary, published_at}]，不关心
底层是 RSS 还是 JSON API。

RSS 解析用标准库 xml.etree.ElementTree，同时兼容 RSS 2.0(<item>) 与
Atom(<entry>)。所有源都在 2026-10-08 实测可达（公共 RSSHub 实例全部不可用，
虎嗅 / V2EX / 知乎 / 微博热搜 从本机不可达，已排除）。
"""

import html as html_mod
import json
import re
import xml.etree.ElementTree as ET

from . import http

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def _local(tag):
    """去掉命名空间前缀：{http://...}title -> title"""
    return tag.split("}")[-1]


def _clean(text, limit=300):
    if not text:
        return ""
    t = TAG_RE.sub(" ", text)
    t = html_mod.unescape(t)
    t = WS_RE.sub(" ", t).strip()
    return t[:limit]


def parse_feed(raw, limit=40):
    """解析 RSS 2.0 / Atom，返回候选列表。"""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise ValueError("XML 解析失败: %s" % e)

    out = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue

        title = link = desc = pub = ""
        for ch in el:
            name = _local(ch.tag)
            if name == "title":
                title = _clean(ch.text or "", 200)
            elif name == "link":
                link = (ch.text or "").strip() or (ch.get("href") or "").strip()
            elif name in ("description", "summary", "content", "encoded"):
                if not desc:
                    desc = _clean(ch.text or "", 300)
            elif name in ("pubDate", "published", "updated", "date"):
                pub = (ch.text or "").strip()

        if title and link:
            out.append({"title": title, "url": link, "summary": desc,
                        "published_at": pub})
        if len(out) >= limit:
            break
    return out


def fetch_rss(url, limit=40, timeout=20):
    _, text = http.request("GET", url, headers={"User-Agent": "Mozilla/5.0 (wmpb)"},
                           timeout=timeout, retries=2)
    return parse_feed(text, limit=limit)


def fetch_hn(url, limit=30, timeout=20):
    """Hacker News（Algolia API）：科技/工程向，英文。"""
    data = http.get_json(url, timeout=timeout, retries=2)
    out = []
    for hit in (data.get("hits") or [])[:limit]:
        title = hit.get("title") or hit.get("story_title") or ""
        link = hit.get("url") or ("https://news.ycombinator.com/item?id=%s" % hit.get("objectID"))
        if title:
            out.append({
                "title": title,
                "url": link,
                "summary": _clean(hit.get("story_text") or "", 200),
                "published_at": hit.get("created_at") or "",
                "points": hit.get("points") or 0,
            })
    return out


def fetch_juejin(url, limit=30, timeout=20):
    """掘金热榜：国内技术/职场向。"""
    data = http.get_json(url, timeout=timeout, retries=2)
    out = []
    for row in (data.get("data") or [])[:limit]:
        content = row.get("content") or {}
        title = content.get("title") or ""
        if not title:
            continue
        cid = content.get("content_id") or ""
        out.append({
            "title": _clean(title, 200),
            "url": ("https://juejin.cn/post/%s" % cid) if cid else "https://juejin.cn",
            "summary": _clean(content.get("brief_content") or "", 200),
            "published_at": "",
            "hot": row.get("content_counter", {}).get("hot_rank") or 0,
        })
    return out


# 已实测可达的源。category 是「倾向归类」，最终归类由模型判断。
SOURCES = [
    {"key": "qbitai", "name": "量子位", "type": "rss", "category": "ai",
     "url": "https://www.qbitai.com/feed"},
    {"key": "leiphone", "name": "雷锋网", "type": "rss", "category": "ai",
     "url": "https://www.leiphone.com/feed"},
    {"key": "ithome", "name": "IT之家", "type": "rss", "category": "tech",
     "url": "https://www.ithome.com/rss/"},
    {"key": "sspai", "name": "少数派", "type": "rss", "category": "tech",
     "url": "https://sspai.com/feed"},
    {"key": "tmtpost", "name": "钛媒体", "type": "rss", "category": "internet",
     "url": "https://www.tmtpost.com/feed"},
    {"key": "infoq", "name": "InfoQ中文", "type": "rss", "category": "tech",
     "url": "https://www.infoq.cn/feed"},
    {"key": "oschina", "name": "OSChina", "type": "rss", "category": "tech",
     "url": "https://www.oschina.net/news/rss"},
    {"key": "hn", "name": "HackerNews", "type": "json", "parser": "hn",
     "category": "tech", "url": "https://hn.algolia.com/api/v1/search?tags=front_page"},
    {"key": "juejin", "name": "掘金热榜", "type": "json", "parser": "juejin",
     "category": "workplace",
     "url": "https://api.juejin.cn/content_api/v1/content/article_rank?category_id=1&type=hot"},
]

PARSERS = {"hn": fetch_hn, "juejin": fetch_juejin}
BY_KEY = dict((s["key"], s) for s in SOURCES)


def fetch_one(source, limit=40):
    """拉取单个源。失败抛异常，由调用方决定是否吞掉。"""
    if source["type"] == "rss":
        items = fetch_rss(source["url"], limit=limit)
    else:
        fn = PARSERS.get(source.get("parser", ""))
        if not fn:
            raise ValueError("未知的 parser: %s" % source.get("parser"))
        items = fn(source["url"], limit=limit)

    for it in items:
        it["source"] = source["key"]
        it["source_name"] = source["name"]
        it["source_category"] = source.get("category", "")
    return items


def fetch_all(enabled_keys=None, limit=40):
    """并发拉取所有启用的源。返回 (candidates, errors)。

    单个源失败不影响其它源 —— 内容采集必须容忍部分源挂掉。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    targets = [s for s in SOURCES if not enabled_keys or s["key"] in enabled_keys]
    candidates, errors = [], []

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = dict((pool.submit(fetch_one, s, limit), s) for s in targets)
        for fut in as_completed(futures):
            src = futures[fut]
            try:
                candidates.extend(fut.result())
            except Exception as e:
                errors.append((src["key"], str(e)[:120]))

    return candidates, errors


def dedupe(items):
    """按标题去重，保留先出现的。"""
    seen, out = set(), []
    for it in items:
        key = re.sub(r"\s+", "", it.get("title", "")).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out
