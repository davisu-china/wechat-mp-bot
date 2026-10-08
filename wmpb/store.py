# -*- coding: utf-8 -*-
"""状态库：SQLite（标准库自带，单文件，无运维成本）。

记录每篇文章从选题到发布的全过程，用于去重、排查和统计。
"""

import json
import os
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT NOT NULL,
    title       TEXT NOT NULL,
    hint        TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    used_at     TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_topics_cat ON topics(category, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_topics_uniq ON topics(category, title);

CREATE TABLE IF NOT EXISTS articles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    day         TEXT NOT NULL,
    category    TEXT NOT NULL,
    topic_id    INTEGER,
    title       TEXT NOT NULL,
    digest      TEXT,
    body_md     TEXT,
    body_html   TEXT,
    theme_json  TEXT,
    cover_prompt TEXT,
    status      TEXT NOT NULL DEFAULT 'generated',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_articles_day ON articles(day, status);

CREATE TABLE IF NOT EXISTS assets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  INTEGER NOT NULL,
    kind        TEXT NOT NULL,
    local_path  TEXT,
    media_id    TEXT,
    wx_url      TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_art ON assets(article_id);

CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  INTEGER NOT NULL,
    action      TEXT NOT NULL,
    comment     TEXT,
    actor       TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS publishes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  INTEGER NOT NULL,
    publisher   TEXT NOT NULL,
    media_id    TEXT,
    url         TEXT,
    status      TEXT NOT NULL,
    errcode     INTEGER,
    message     TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pub_art ON publishes(article_id);

CREATE TABLE IF NOT EXISTS llm_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  INTEGER,
    purpose     TEXT,
    model       TEXT,
    prompt_hash TEXT,
    response    TEXT,
    cost_usd    REAL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv (
    k           TEXT PRIMARY KEY,
    v           TEXT,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS candidates (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint  TEXT NOT NULL,
    title        TEXT NOT NULL,
    url          TEXT,
    source       TEXT,
    summary      TEXT,
    published_at TEXT,
    picked       INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cand_fp ON candidates(fingerprint);
CREATE INDEX IF NOT EXISTS idx_cand_picked ON candidates(picked, created_at);
"""


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class Store(object):
    def __init__(self, path):
        d = os.path.dirname(os.path.abspath(path))
        if d and not os.path.isdir(d):
            os.makedirs(d)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ---------- kv ----------
    def kv_get(self, key, default=None):
        row = self.conn.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
        return row["v"] if row else default

    def kv_set(self, key, value):
        self.conn.execute(
            "INSERT OR REPLACE INTO kv(k, v, updated_at) VALUES(?,?,?)",
            (key, value, _now()),
        )
        self.conn.commit()

    # ---------- topics ----------
    def add_topic(self, category, title, hint=""):
        """加入选题池。已存在则忽略（唯一索引保证不重复）。"""
        try:
            self.conn.execute(
                "INSERT INTO topics(category, title, hint, status, created_at) "
                "VALUES(?,?,?, 'pending', ?)",
                (category, title, hint, _now()),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def next_topic(self, category):
        row = self.conn.execute(
            "SELECT * FROM topics WHERE category=? AND status='pending' "
            "ORDER BY id LIMIT 1", (category,)
        ).fetchone()
        if not row:
            return None
        self.conn.execute(
            "UPDATE topics SET status='used', used_at=? WHERE id=?",
            (_now(), row["id"]),
        )
        self.conn.commit()
        return dict(row)

    def recent_titles(self, days=30, limit=50):
        """近期已用过的标题，用于让模型避免重复。"""
        rows = self.conn.execute(
            "SELECT title FROM articles ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [r["title"] for r in rows]

    # ---------- articles ----------
    def create_article(self, day, category, topic_id, title, digest, body_md,
                       body_html="", theme=None, cover_prompt=""):
        cur = self.conn.execute(
            "INSERT INTO articles(day, category, topic_id, title, digest, body_md, "
            "body_html, theme_json, cover_prompt, status, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?, 'generated', ?, ?)",
            (day, category, topic_id, title, digest, body_md, body_html,
             json.dumps(theme or {}, ensure_ascii=False), cover_prompt, _now(), _now()),
        )
        self.conn.commit()
        return cur.lastrowid

    def update_article(self, article_id, **fields):
        if not fields:
            return
        fields["updated_at"] = _now()
        cols = ", ".join("%s=?" % k for k in fields)
        self.conn.execute(
            "UPDATE articles SET %s WHERE id=?" % cols,
            list(fields.values()) + [article_id],
        )
        self.conn.commit()

    def get_article(self, article_id):
        row = self.conn.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
        return dict(row) if row else None

    def get_article_by_day(self, day):
        row = self.conn.execute(
            "SELECT * FROM articles WHERE day=? ORDER BY id DESC LIMIT 1", (day,)
        ).fetchone()
        return dict(row) if row else None

    # ---------- candidates ----------
    def save_candidates(self, items):
        """写入候选。返回新增条数（重复的靠唯一索引跳过）。"""
        added = 0
        for it in items:
            import hashlib
            fp = hashlib.sha1(
                (it.get("title", "") + "|" + it.get("url", "")).encode("utf-8")
            ).hexdigest()[:20]
            try:
                self.conn.execute(
                    "INSERT INTO candidates(fingerprint, title, url, source, summary, "
                    "published_at, created_at) VALUES(?,?,?,?,?,?,?)",
                    (fp, it.get("title", ""), it.get("url", ""), it.get("source", ""),
                     it.get("summary", ""), it.get("published_at", ""), _now()),
                )
                added += 1
            except sqlite3.IntegrityError:
                pass
        self.conn.commit()
        return added

    def unpicked_candidates(self, limit=80):
        rows = self.conn.execute(
            "SELECT * FROM candidates WHERE picked=0 ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_candidates_picked(self, ids):
        if not ids:
            return
        marks = ",".join("?" * len(ids))
        self.conn.execute(
            "UPDATE candidates SET picked=1 WHERE id IN (%s)" % marks, list(ids)
        )
        self.conn.commit()

    def purge_old_candidates(self, keep_days=14):
        """清掉过期的未选候选，避免表无限膨胀。"""
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%S",
                               time.gmtime(time.time() - keep_days * 86400))
        cur = self.conn.execute(
            "DELETE FROM candidates WHERE picked=0 AND created_at < ?", (cutoff,))
        self.conn.commit()
        return cur.rowcount

    # ---------- logs ----------
    def log_llm(self, article_id, purpose, model, prompt_hash, response, cost=0.0):
        self.conn.execute(
            "INSERT INTO llm_calls(article_id, purpose, model, prompt_hash, response, "
            "cost_usd, created_at) VALUES(?,?,?,?,?,?,?)",
            (article_id, purpose, model, prompt_hash, response, cost, _now()),
        )
        self.conn.commit()

    def log_publish(self, article_id, publisher, status, media_id="", url="",
                    errcode=None, message=""):
        self.conn.execute(
            "INSERT INTO publishes(article_id, publisher, media_id, url, status, "
            "errcode, message, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (article_id, publisher, media_id, url, status, errcode, message, _now()),
        )
        self.conn.commit()

    def log_asset(self, article_id, kind, local_path="", media_id="", wx_url=""):
        self.conn.execute(
            "INSERT INTO assets(article_id, kind, local_path, media_id, wx_url, created_at) "
            "VALUES(?,?,?,?,?,?)",
            (article_id, kind, local_path, media_id, wx_url, _now()),
        )
        self.conn.commit()
