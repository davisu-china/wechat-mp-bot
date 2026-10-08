# -*- coding: utf-8 -*-
"""选题模块。

MVP 采用「配置化栏目 + 选题池」：
  1. 按栏目权重轮换挑一个栏目（避免连续同栏目）
  2. 从该栏目的 pending 选题里取最早一条
  3. 池子空了则让模型现场生成候选，写回池子

不做大规模抓取 —— 选题质量靠人喂 + 模型补，不靠爬。
"""

import json
import os
import random


def load_pool(path):
    """读取选题池文件，返回 {category: [ {title, hint}, ... ]}"""
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        return json.load(f)


def seed_pool(store, path):
    """把选题池文件灌进数据库（幂等，已存在的跳过）。"""
    pool = load_pool(path)
    added = 0
    for category, items in pool.items():
        for item in items:
            title = item if isinstance(item, str) else item.get("title", "")
            hint = "" if isinstance(item, str) else item.get("hint", "")
            if title and store.add_topic(category, title, hint):
                added += 1
    return added


def pick_category(cfg, store):
    """按权重轮换选栏目，并尽量避开上一次用的栏目。"""
    categories = cfg.get("categories") or []
    if not categories:
        raise ValueError("配置里没有任何栏目")

    last = store.kv_get("last_category", "")
    weighted = []
    for c in categories:
        if c.get("key") == last and len(categories) > 1:
            continue  # 本轮跳过，避免连续同栏目
        weighted.extend([c] * max(1, int(c.get("weight", 1))))

    chosen = random.choice(weighted) if weighted else random.choice(categories)
    store.kv_set("last_category", chosen.get("key", ""))
    return chosen


def pick_topic(cfg, store, category):
    """取一条选题。池子空了返回 None，由调用方决定是否让模型生成。"""
    return store.next_topic(category.get("key"))


def add_candidates(store, category_key, titles):
    """把模型生成的候选选题写回池子。"""
    added = 0
    for t in titles:
        t = (t or "").strip()
        if t and len(t) < 80 and store.add_topic(category_key, t):
            added += 1
    return added
