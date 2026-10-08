# -*- coding: utf-8 -*-
"""选题采集：从内容源拉取候选 -> 模型筛选并改写成可写的选题 -> 入选题池。

为什么不让程序直接按关键词归类：
  一条新闻该归到「AI」还是「互联网职场」，取决于它的**切入角度**，
  而不是标题里出现了什么词。所以归类交给模型判断，程序只负责
  把候选洗干净、去重、控制数量。
"""

import json

from . import generate, sources as sources_mod
from .generate import LLMClient, _extract_json

SELECT_SYSTEM = """你是公众号选题编辑。我会给你一批当天抓到的新闻标题，你要从中挑出值得写成公众号文章的选题。

选题标准：
- 有明确的信息量或观点价值，不是纯公告、纯发布会通稿
- 读者（技术从业者）会关心
- 能支撑一篇 800-1500 字的文章

对每条入选，你要给出：
- title：改写成**可写的选题**，不是照抄新闻标题。要带上角度。
- category：必须是下面给到的栏目 key 之一
- hint：一句话说明切入角度
- score：0-10 分，你的推荐度
- ref：对应的候选序号（整数）

只输出 JSON 数组，不要解释、不要用 ``` 包裹。例如：
[{"title":"...","category":"ai","hint":"...","score":9,"ref":3}]"""


def _fallback_pick(candidates, categories, per_category):
    """模型不可用时的降级：按源自身的归类倾向直接收标题。

    注意：候选从数据库读回来时没有 source_category 字段（那个字段只在
    抓取时的内存对象上），所以这里按 source key 回注册表反查。
    """
    by_cat = {}
    valid = set(c.get("key") for c in categories)
    for c in candidates:
        src = sources_mod.BY_KEY.get(c.get("source") or "", {})
        cat = c.get("source_category") or src.get("category") or ""
        if cat not in valid:
            continue
        by_cat.setdefault(cat, [])
        if len(by_cat[cat]) < per_category:
            by_cat[cat].append({
                "title": c.get("title", ""),
                "category": cat,
                "hint": (c.get("summary") or "")[:80],
                "score": 5,
                "ref": None,
            })
    out = []
    for v in by_cat.values():
        out.extend(v)
    return out


def select_topics(cfg, st, candidates, categories, per_category=6, model=None):
    """让模型从候选里挑选题并归类。失败时降级为按源归类。"""
    if not candidates:
        return [], "没有候选"

    valid_keys = [c.get("key") for c in categories]
    cat_desc = "、".join("%s（%s）" % (c.get("key"), c.get("name")) for c in categories)

    lines = []
    for i, c in enumerate(candidates):
        summary = (c.get("summary") or "")[:80]
        lines.append("%d. [%s] %s%s" % (
            i, c.get("source_name") or c.get("source"),
            c.get("title"), (" —— " + summary) if summary else ""))

    user_prompt = (
        "栏目（category 只能取这些 key）：%s\n"
        "每个栏目最多挑 %d 条。\n\n"
        "今日候选：\n%s" % (cat_desc, per_category, "\n".join(lines))
    )

    try:
        client = LLMClient(cfg)
        content, usage = client.chat([
            {"role": "system", "content": SELECT_SYSTEM},
            {"role": "user", "content": user_prompt},
        ], temperature=0.5, max_tokens=4000)

        data = _extract_json(content)
        if isinstance(data, dict):
            data = data.get("topics", [])
        if not isinstance(data, list):
            raise ValueError("模型输出不是数组")

        picked = []
        used_per_cat = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            cat = item.get("category")
            title = (item.get("title") or "").strip()
            if cat not in valid_keys or not title:
                continue
            used_per_cat[cat] = used_per_cat.get(cat, 0) + 1
            if used_per_cat[cat] > per_category:
                continue
            picked.append({
                "title": title,
                "category": cat,
                "hint": (item.get("hint") or "").strip(),
                "score": item.get("score", 0),
                "ref": item.get("ref"),
            })

        if not picked:
            raise ValueError("模型没有挑出任何选题")

        st.log_llm(None, "select", client.model, "", content,
                   client.estimate_cost(usage))
        return picked, "ok"

    except Exception as e:
        st.log_llm(None, "select_failed", cfg.get("llm.model"), "", str(e)[:500], 0.0)
        return _fallback_pick(candidates, categories, per_category), "降级：%s" % str(e)[:100]


def collect(cfg, st, source_keys=None, limit=40, per_category=6):
    """跑一次采集。返回统计信息。"""
    enabled = source_keys or cfg.get("collect.sources") or None

    items, errors = sources_mod.fetch_all(enabled_keys=enabled, limit=limit)
    items = sources_mod.dedupe(items)
    added = st.save_candidates(items)
    st.purge_old_candidates()

    candidates = st.unpicked_candidates(int(cfg.get("collect.batch", 80)))
    picked, status = select_topics(cfg, st, candidates, cfg.get("categories"),
                                   per_category=per_category)

    written = 0
    for t in picked:
        if st.add_topic(t["category"], t["title"], t.get("hint", "")):
            written += 1

    # 把被模型选中过的候选标记掉，避免下次重复喂进去
    ref_ids = []
    for t in picked:
        ref = t.get("ref")
        if isinstance(ref, int) and 0 <= ref < len(candidates):
            ref_ids.append(candidates[ref]["id"])
    st.mark_candidates_picked(ref_ids)

    return {
        "fetched": len(items),
        "new_candidates": added,
        "pool_size": len(candidates),
        "picked": len(picked),
        "written": written,
        "status": status,
        "errors": errors,
    }
