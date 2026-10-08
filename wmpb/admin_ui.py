# -*- coding: utf-8 -*-
"""后台页面的 HTML 渲染。

全部内联在 Python 里 —— 不引入模板引擎、不引入前端构建。
页面按手机优先设计：这个后台大概率是在手机浏览器上打开的。
"""

import html as html_mod
import time

CSS = """
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:#F3F4F7;color:#131722;
     font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
     font-size:15px;line-height:1.7;padding-bottom:64px}
a{color:#2C4A8C;text-decoration:none}
.top{background:#1E3568;color:#fff;padding:14px 18px;display:flex;align-items:center;
     justify-content:space-between;position:sticky;top:0;z-index:10}
.top h1{margin:0;font-size:16px;font-weight:600;letter-spacing:.02em}
.top .who{font-size:12px;opacity:.75}
.nav{background:#fff;border-bottom:1px solid #E5E7EE;display:flex;overflow-x:auto;
     position:sticky;top:52px;z-index:9}
.nav a{padding:12px 16px;font-size:14px;color:#5C6577;white-space:nowrap;border-bottom:2px solid transparent}
.nav a.on{color:#2C4A8C;border-bottom-color:#2C4A8C;font-weight:600}
.wrap{max-width:860px;margin:0 auto;padding:16px}
.card{background:#fff;border:1px solid #E5E7EE;border-radius:10px;padding:16px;margin-bottom:14px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px}
.stat{background:#fff;border:1px solid #E5E7EE;border-radius:10px;padding:12px;text-align:center}
.stat b{display:block;font-size:22px;color:#1E3568;line-height:1.3}
.stat span{font-size:11px;color:#8A8F99}
h2{font-size:15px;margin:0 0 12px;color:#1E3568}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;font-size:11px;color:#8A8F99;text-transform:uppercase;
   letter-spacing:.06em;padding:6px 8px;border-bottom:1px solid #E5E7EE;font-weight:600}
td{padding:10px 8px;border-bottom:1px solid #F0F1F4;vertical-align:top}
tr:last-child td{border-bottom:none}
.pill{display:inline-block;font-size:11px;padding:1px 7px;border-radius:20px;
      background:#EEF1F6;color:#5C6577;white-space:nowrap}
.pill.ai{background:#E3EDFB;color:#1B4F72}
.pill.tech{background:#E2F0EE;color:#0F6157}
.pill.internet{background:#F3E9DC;color:#8A6412}
.pill.workplace{background:#EFE4F2;color:#6B3A78}
.pill.generated{background:#E3EDFB;color:#1B4F72}
.pill.published{background:#E2F0EE;color:#0F6157}
.pill.rejected{background:#F7E4E0;color:#9C3A28}
.btn{display:inline-block;padding:6px 12px;border-radius:6px;font-size:12.5px;
     border:1px solid #D7DAE3;background:#fff;color:#333A4A;cursor:pointer;
     font-family:inherit;line-height:1.5}
.btn.primary{background:#2C4A8C;border-color:#2C4A8C;color:#fff}
.btn.danger{color:#9C3A28;border-color:#E8CFC9}
.btn:active{opacity:.7}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.muted{color:#8A8F99;font-size:12.5px}
.empty{text-align:center;color:#8A8F99;padding:40px 0;font-size:13.5px}
.flash{background:#E2F0EE;color:#0F6157;border:1px solid #C3DED9;border-radius:8px;
       padding:10px 14px;margin-bottom:14px;font-size:13.5px}
.flash.err{background:#F7E4E0;color:#9C3A28;border-color:#E8CFC9}
input[type=text],input[type=password],select,textarea{
    width:100%;padding:9px 11px;border:1px solid #D7DAE3;border-radius:7px;
    font-size:14px;font-family:inherit;background:#fff}
label{display:block;font-size:12.5px;color:#5C6577;margin:10px 0 4px}
.login{max-width:340px;margin:80px auto;padding:0 20px}
.login h1{font-size:20px;text-align:center;margin:0 0 6px;color:#1E3568}
.login p{text-align:center;color:#8A8F99;font-size:13px;margin:0 0 24px}
.phone{max-width:375px;margin:0 auto;background:#fff;border-radius:14px;
       box-shadow:0 8px 30px rgba(0,0,0,.12);overflow:hidden}
.phone .bar{background:#FAFAFB;border-bottom:1px solid #ECEEF1;padding:8px 14px;
            font-size:11.5px;color:#8A8F99;text-align:center}
.phone .body{padding:18px 16px 36px}
.tip{font-size:12.5px;color:#8A8F99;margin-top:10px}
"""


def _e(s):
    return html_mod.escape(str(s if s is not None else ""), quote=True)


def page(title, body, active="", who="", flash=None, flash_err=False):
    nav = [("/", "概览"), ("/topics", "选题池"), ("/articles", "文章"),
           ("/publish", "发布记录")]
    nav_html = "".join(
        '<a href="%s" class="%s">%s</a>' % (u, "on" if active == u else "", _e(t))
        for u, t in nav)

    flash_html = ""
    if flash:
        flash_html = '<div class="flash%s">%s</div>' % (" err" if flash_err else "", _e(flash))

    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>%s · wechat-mp-bot</title><style>%s</style></head><body>'
        '<div class="top"><h1>wechat-mp-bot</h1>'
        '<span class="who">%s <a href="/logout" style="color:#9DB4D8">退出</a></span></div>'
        '<div class="nav">%s</div>'
        '<div class="wrap">%s%s</div>'
        '</body></html>' % (_e(title), CSS, _e(who), nav_html, flash_html, body))


def login_page(error=None):
    err = '<div class="flash err">%s</div>' % _e(error) if error else ""
    return (
        '<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>登录 · wechat-mp-bot</title><style>%s</style></head><body>'
        '<div class="login"><h1>wechat-mp-bot</h1>'
        '<p>每日公众号推文后台</p>%s'
        '<form method="post" action="/login">'
        '<label>访问密码</label>'
        '<input type="password" name="password" autofocus autocomplete="current-password">'
        '<div style="margin-top:16px"><button class="btn primary" '
        'style="width:100%%;padding:11px">进入</button></div>'
        '</form></div></body></html>' % (CSS, err))


def _pill(value, cls=None):
    return '<span class="pill %s">%s</span>' % (_e(cls or ""), _e(value))


def dashboard(stats, recent, latest=None):
    cards = "".join(
        '<div class="stat"><b>%s</b><span>%s</span></div>' % (_e(v), _e(k))
        for k, v in stats)

    rows = "".join(
        '<tr><td><a href="/articles/%d">%s</a><div class="muted">%s · %s</div></td>'
        '<td style="text-align:right">%s</td></tr>'
        % (a["id"], _e(a["title"][:40]), _e(a["category"]), _e(a["day"]),
           _pill(a["status"], a["status"]))
        for a in recent) or '<tr><td colspan="2" class="empty">还没有文章</td></tr>'

    actions = (
        '<div class="card"><h2>手动触发</h2>'
        '<div class="row">'
        '<form method="post" action="/actions/collect" style="display:inline">'
        '<button class="btn primary">采集选题</button></form>'
        '<form method="post" action="/actions/generate" style="display:inline">'
        '<button class="btn">生成一篇</button></form>'
        '</div>'
        '<div class="tip">采集约 20 秒，生成一篇约 15 秒。生成结果会出现在「文章」里。</div>'
        '</div>')

    body = '<div class="stats">%s</div>%s<div class="card"><h2>最近文章</h2>' \
           '<table>%s</table></div>' % (cards, actions, rows)
    return body


def topics_page(categories, topics, counts):
    opts = "".join('<option value="%s">%s</option>' % (_e(c["key"]), _e(c["name"]))
                   for c in categories)
    add_form = (
        '<div class="card"><h2>添加选题</h2>'
        '<form method="post" action="/topics/add">'
        '<label>栏目</label><select name="category">%s</select>'
        '<label>选题</label><input type="text" name="title" placeholder="这条选题要写什么">'
        '<label>切入角度（可选）</label><input type="text" name="hint">'
        '<div style="margin-top:14px"><button class="btn primary">加入选题池</button></div>'
        '</form></div>' % opts)

    rows = ""
    for t in topics:
        rows += (
            '<tr><td>%s<div class="muted">%s</div></td>'
            '<td style="width:1%%;white-space:nowrap;text-align:right">'
            '<form method="post" action="/topics/delete" style="display:inline">'
            '<input type="hidden" name="id" value="%d">'
            '<button class="btn danger">删</button></form></td></tr>'
            % (_e(t["title"]),
               _pill(_name_of(categories, t["category"]), t["category"])
               + ((" · " + _e(t["hint"][:60])) if t.get("hint") else ""),
               t["id"]))

    table = ('<div class="card"><h2>待用选题（%d）</h2><table>%s</table></div>'
             % (len(topics), rows)) if rows else \
            add_form + '<div class="card"><div class="empty">选题池是空的，先去概览页点「采集选题」</div></div>'

    return add_form + table


def _name_of(categories, key):
    for c in categories:
        if c.get("key") == key:
            return c.get("name", key)
    return key


def articles_page(articles):
    rows = "".join(
        '<tr><td><a href="/articles/%d">%s</a>'
        '<div class="muted">%s · %s · %s 字</div></td>'
        '<td style="text-align:right;width:1%%;white-space:nowrap">%s</td></tr>'
        % (a["id"], _e(a["title"][:44]), _e(a["category"]), _e(a["day"]),
           _e(len(a.get("body_md") or "")), _pill(a["status"], a["status"]))
        for a in articles)
    if not rows:
        return '<div class="card"><div class="empty">还没有生成过文章</div></div>'
    return '<div class="card"><table>%s</table></div>' % rows


def article_detail(a, preview_html, paste_url):
    actions = (
        '<div class="card"><h2>操作</h2><div class="row">'
        '<a class="btn primary" href="%s" target="_blank">打开粘贴页</a>'
        '<form method="post" action="/articles/%d/status" style="display:inline">'
        '<input type="hidden" name="status" value="reviewed">'
        '<button class="btn">标记已审</button></form>'
        '<form method="post" action="/articles/%d/status" style="display:inline">'
        '<input type="hidden" name="status" value="rejected">'
        '<button class="btn danger">弃用</button></form>'
        '</div><div class="tip">「粘贴页」打开后 Ctrl+A / Ctrl+C，可直接粘进公众号编辑器，'
        '样式不会丢。</div></div>' % (paste_url, a["id"], a["id"]))

    meta = ('<div class="card"><h2>%s</h2>'
            '<div class="muted">%s · %s · %s</div>'
            '<p style="margin:10px 0 0;font-size:13.5px;color:#333A4A">%s</p>'
            '</div>' % (_e(a["title"]), _e(a["category"]), _e(a["day"]),
                        _pill(a["status"], a["status"]), _e(a.get("digest") or "")))

    preview = '<div class="phone"><div class="bar">公众号预览</div>' \
              '<div class="body">%s</div></div>' % preview_html

    return meta + actions + preview


def publish_page(rows):
    if not rows:
        return '<div class="card"><div class="empty">还没有发布记录</div></div>'
    body = "".join(
        '<tr><td>%s<div class="muted">%s · %s</div></td>'
        '<td style="text-align:right">%s</td></tr>'
        % (_e(r["publisher"]), _e(r["created_at"]), _e(r.get("message") or ""),
           _pill(r["status"]))
        for r in rows)
    return '<div class="card"><table>%s</table></div>' % body


def render_article_body(a):
    """文章正文在后台里的展示：直接用它自己渲染好的 HTML，
    外面包一层手机壳。这里不用再套样式，正文本来就是全内联样式的。"""
    return '<h1 style="font-size:20px;line-height:1.4;margin:0 0 14px;color:#1A1A1A">%s</h1>%s' \
           % (_e(a["title"]), a.get("body_html") or "<p>（没有正文）</p>")
