#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wechat-mp-bot 命令行入口。

用法：
  python3.6 run.py seed              # 把选题池灌进数据库
  python3.6 run.py preview           # 生成一篇 + 出本地预览，不发布
  python3.6 run.py run               # 跑全流程（生成 -> 排版 -> 审核 -> 发布）
  python3.6 run.py publish --id 3    # 对已生成的稿子重新提交发布
"""

import argparse
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from wmpb import config as config_mod
from wmpb import generate, render, store as store_mod, topic as topic_mod


def _log(msg):
    sys.stdout.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stdout.flush()


def _write(path, text):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "w") as f:
        f.write(text)
    return path


def build_article(cfg, st, category):
    """选题 -> 生成 -> 排版。返回 (article_dict, topic_row)。"""
    recent = st.recent_titles()

    topic_row = topic_mod.pick_topic(cfg, st, category)
    if topic_row is None:
        _log("选题池为空，让模型现场出一批候选…")
        try:
            titles = generate.generate_topics(cfg, category, n=5, recent_titles=recent)
            added = topic_mod.add_candidates(st, category.get("key"), titles)
            _log("新增候选选题 %d 条" % added)
        except Exception as e:
            _log("候选选题生成失败（继续走自由发挥）：%s" % e)
        topic_row = topic_mod.pick_topic(cfg, st, category)

    _log("栏目：%s" % category.get("name"))
    _log("选题：%s" % (topic_row["title"] if topic_row else "（自由发挥）"))

    _log("调用 %s 生成中…" % cfg.get("llm.model"))
    art = generate.generate_article(cfg, st, category, topic_row, recent)
    _log("标题：%s" % art["title"])
    _log("成本估算：$%.6f" % art.get("_cost", 0))

    art["html"] = render.render_article_html(art["body_md"], art["theme"])
    return art, topic_row


def cmd_preview(args):
    cfg = config_mod.load(args.config)
    st = store_mod.Store(cfg.abs_path("paths.state_db"))
    try:
        if args.category:
            categories = [c for c in cfg.get("categories") if c.get("key") == args.category]
            if not categories:
                _log("没有找到栏目：%s" % args.category)
                return 1
            category = categories[0]
        else:
            category = topic_mod.pick_category(cfg, st)

        art, topic_row = build_article(cfg, st, category)

        day = time.strftime("%Y-%m-%d")
        ws = cfg.abs_path("paths.workspace")
        preview_path = os.path.join(ws, "preview", "%s.html" % day)
        paste_path = os.path.join(ws, "preview", "%s.paste.html" % day)

        _write(preview_path,
               render.render_preview_page(art["title"], art["digest"], art["html"],
                                          art["theme"],
                                          meta={"栏目": category.get("name"),
                                                "选题": topic_row["title"] if topic_row else "-",
                                                "模型": cfg.get("llm.model")}))
        _write(paste_path, render.render_paste_page(art["title"], art["html"]))

        if not args.no_save:
            art_id = st.create_article(
                day, category.get("key"), topic_row["id"] if topic_row else None,
                art["title"], art["digest"], art["body_md"], art["html"],
                art["theme"], art["cover_prompt"])
            _log("已入库，article id=%s" % art_id)

        _log("预览页：%s" % preview_path)
        _log("粘贴页：%s  （打开后 Ctrl+A / Ctrl+C，可直接粘进公众号编辑器）" % paste_path)
        return 0
    finally:
        st.close()


def cmd_seed(args):
    cfg = config_mod.load(args.config)
    st = store_mod.Store(cfg.abs_path("paths.state_db"))
    try:
        pool = cfg.abs_path("paths.topic_pool")
        added = topic_mod.seed_pool(st, pool)
        _log("从 %s 导入选题 %d 条" % (pool, added))
        return 0
    finally:
        st.close()


def cmd_run(args):
    _log("全流程模式：微信发布部分待 M2 接入")
    return cmd_preview(args)


def cmd_publish(args):
    _log("发布功能待 M2 接入（需要 AppID/AppSecret 与 IP 白名单）")
    return 1


def main():
    p = argparse.ArgumentParser(prog="run.py", description="每日生成微信公众号推文")
    p.add_argument("--config", default=None, help="配置文件路径")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("preview", help="生成一篇并出本地预览（不发布）")
    sp.add_argument("--category", default=None, help="指定栏目 key")
    sp.add_argument("--no-save", action="store_true", help="不入库")
    sp.set_defaults(func=cmd_preview)

    ss = sub.add_parser("seed", help="把选题池灌进数据库")
    ss.set_defaults(func=cmd_seed)

    sr = sub.add_parser("run", help="跑全流程")
    sr.add_argument("--category", default=None)
    sr.add_argument("--no-save", action="store_true")
    sr.set_defaults(func=cmd_run)

    sb = sub.add_parser("publish", help="重新提交发布")
    sb.add_argument("--id", type=int, required=True)
    sb.set_defaults(func=cmd_publish)

    args = p.parse_args()
    if not getattr(args, "cmd", None):
        p.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
