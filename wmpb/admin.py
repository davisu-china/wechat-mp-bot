# -*- coding: utf-8 -*-
"""后台服务。

纯标准库实现的轻量 Web 后台（http.server + SQLite），零依赖。

安全前提（很重要）：
  1. **必须配置密码**，没配就拒绝启动。这个后台能触发生成、能看全部文章，
     挂到公网上没密码等于把控制权交出去。
  2. 建议只监听 127.0.0.1，由外层 nginx 反代并加 HTTPS；不要直接暴露到公网。
  3. 会话用 HMAC 签名的 cookie，签名密钥随机生成后落在状态库里，重启不掉线。

动作类接口（采集 / 生成）跑在后台线程：这两个操作分别要十几到二十几秒，
同步跑会让浏览器一直转圈。改成后台线程 + 概览页轮询任务状态。
"""

import hashlib
import hmac
import json
import os
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

from . import admin_ui as ui
from . import collect as collect_mod
from . import generate, render
from . import config as config_mod
from . import store as store_mod
from . import topic as topic_mod

COOKIE = "wmpb_session"
TASKS = {}          # name -> {status, msg, started, ended}
TASK_LOCK = threading.Lock()


# ---------------------------------------------------------------- 认证

def _session_token(secret):
    return hmac.new(secret.encode("utf-8"), b"wmpb-session-v1",
                    hashlib.sha256).hexdigest()


def _session_secret(cfg, st):
    """签名密钥：首次随机生成后持久化，避免重启后所有人被登出。"""
    s = st.kv_get("admin_session_secret")
    if not s:
        s = hashlib.sha256(os.urandom(32)).hexdigest()
        st.kv_set("admin_session_secret", s)
    return s


# ---------------------------------------------------------------- 动作

def _run_task(name, fn):
    """在后台线程里跑一个动作，状态记在 TASKS 里供页面轮询。"""
    with TASK_LOCK:
        cur = TASKS.get(name)
        if cur and cur["status"] == "running":
            return False
        TASKS[name] = {"status": "running", "msg": "执行中…",
                       "started": time.time(), "ended": None}

    def worker():
        try:
            msg = fn()
            TASKS[name].update(status="done", msg=msg or "完成", ended=time.time())
        except Exception as e:
            TASKS[name].update(status="error", msg=str(e)[:300], ended=time.time())

    t = threading.Thread(target=worker)
    t.daemon = True
    t.start()
    return True


def _task_status():
    out = []
    for name, t in sorted(TASKS.items()):
        label = {"collect": "采集选题", "generate": "生成文章"}.get(name, name)
        out.append({"name": name, "label": label, "status": t["status"],
                    "msg": t["msg"], "started": t["started"]})
    return out


# ---------------------------------------------------------------- 请求处理

class Handler(BaseHTTPRequestHandler):
    server_version = "wmpb-admin"

    # 由 make_server 注入
    cfg = None
    secret = None

    def log_message(self, fmt, *args):
        # 默认会往 stderr 打每条请求，太吵；只记异常路径由 _send 负责
        pass

    # ---------- 工具 ----------

    def _send(self, body, code=200, ctype="text/html; charset=utf-8", headers=None):
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _redirect(self, to, flash=None, err=False, cookie=None):
        headers = {}
        if flash:
            headers["Set-Cookie"] = "wmpb_flash=%s; Path=/; Max-Age=20; SameSite=Lax" % (
                urllib.parse.quote(("!" if err else "") + flash))
        if cookie:
            headers["Set-Cookie"] = cookie
        self.send_response(303)
        self.send_header("Location", to)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _cookies(self):
        raw = self.headers.get("Cookie", "")
        out = {}
        for part in raw.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                out[k] = urllib.parse.unquote(v)
        return out

    def _authed(self):
        return self._cookies().get(COOKIE) == _session_token(self.secret)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return {}
        raw = self.rfile.read(n).decode("utf-8", "replace")
        return dict((k, v[0]) for k, v in urllib.parse.parse_qs(raw).items())

    def _st(self):
        return store_mod.Store(self.cfg.abs_path("paths.state_db"))

    # ---------- 路由 ----------

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/login":
            return self._send(ui.login_page())
        if path == "/logout":
            return self._redirect("/login", cookie="%s=; Path=/; Max-Age=0" % COOKIE)
        if path == "/favicon.ico":
            return self._send("", 204)

        if not self._authed():
            return self._redirect("/login")

        try:
            if path == "/":
                return self._page_dashboard()
            if path == "/topics":
                return self._page_topics()
            if path == "/articles":
                return self._page_articles()
            if path == "/publish":
                return self._page_publish()
            if path.startswith("/articles/"):
                rest = path[len("/articles/"):]
                if rest.endswith("/paste"):
                    return self._page_paste(rest[:-len("/paste")])
                return self._page_article(rest)
            return self._send(ui.page("404", '<div class="card">页面不存在</div>',
                                      flash="没有这个页面", flash_err=True), 404)
        except Exception as e:
            return self._send(ui.page("错误",
                '<div class="card"><h2>出错了</h2><pre style="white-space:pre-wrap;'
                'font-size:12.5px">%s</pre></div>' % ui._e(e), flash=str(e)[:200],
                flash_err=True), 500)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        form = self._body()

        if path == "/login":
            pw = form.get("password", "")
            if self.cfg.get("admin.password") and pw == self.cfg.get("admin.password"):
                ck = "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d" % (
                    COOKIE, _session_token(self.secret), 60 * 60 * 24 * 14)
                return self._redirect("/", cookie=ck)
            time.sleep(1.0)   # 减缓暴力尝试
            return self._send(ui.login_page("密码不对"), 401)

        if not self._authed():
            return self._redirect("/login")

        try:
            if path == "/topics/add":
                st = self._st()
                try:
                    ok = st.add_topic(form.get("category", ""), form.get("title", "").strip(),
                                      form.get("hint", "").strip())
                finally:
                    st.close()
                return self._redirect("/topics",
                                      "已加入选题池" if ok else "这条选题已存在")

            if path == "/topics/delete":
                st = self._st()
                try:
                    st.conn.execute("DELETE FROM topics WHERE id=?", (form.get("id"),))
                    st.conn.commit()
                finally:
                    st.close()
                return self._redirect("/topics", "已删除")

            if path.startswith("/articles/") and path.endswith("/status"):
                aid = path[len("/articles/"):-len("/status")]
                st = self._st()
                try:
                    st.update_article(int(aid), status=form.get("status", ""))
                finally:
                    st.close()
                return self._redirect("/articles/%s" % aid, "状态已更新")

            if path == "/actions/collect":
                started = _run_task("collect", self._do_collect)
                return self._redirect("/", "采集已启动" if started else "采集正在跑，别急")

            if path == "/actions/generate":
                started = _run_task("generate", self._do_generate)
                return self._redirect("/", "生成已启动" if started else "生成正在跑，别急")

            return self._send("not found", 404, "text/plain; charset=utf-8")
        except Exception as e:
            return self._redirect("/", "操作失败：%s" % str(e)[:150], err=True)

    # ---------- 动作实现 ----------

    def _do_collect(self):
        cfg, st = self.cfg, self._st()
        try:
            stats = collect_mod.collect(
                cfg, st,
                limit=int(cfg.get("collect.limit", 40)),
                per_category=int(cfg.get("collect.per_category", 6)))
            return "抓取 %d 条，新入选题池 %d 条" % (stats["fetched"], stats["written"])
        finally:
            st.close()

    def _do_generate(self):
        cfg, st = self.cfg, self._st()
        try:
            cat = topic_mod.pick_category(cfg, st)
            topic_row = topic_mod.pick_topic(cfg, st, cat)
            if topic_row is None:
                try:
                    titles = generate.generate_topics(cfg, cat, n=5,
                                                      recent_titles=st.recent_titles())
                    topic_mod.add_candidates(st, cat.get("key"), titles)
                except Exception:
                    pass
                topic_row = topic_mod.pick_topic(cfg, st, cat)

            art = generate.generate_article(cfg, st, cat, topic_row, st.recent_titles())
            html = render.render_article_html(art["body_md"], art["theme"])
            day = time.strftime("%Y-%m-%d")
            aid = st.create_article(day, cat.get("key"),
                                    topic_row["id"] if topic_row else None,
                                    art["title"], art["digest"], art["body_md"],
                                    html, art["theme"], art["cover_prompt"])
            # 同时落一份粘贴页，供后台直接下载/打开
            ws = cfg.abs_path("paths.workspace")
            pdir = os.path.join(ws, "preview")
            if not os.path.isdir(pdir):
                os.makedirs(pdir)
            with open(os.path.join(pdir, "%s.paste.html" % day), "w") as f:
                f.write(render.render_paste_page(art["title"], html))
            return "已生成：%s" % art["title"][:30]
        finally:
            st.close()

    # ---------- 页面 ----------

    def _flash(self):
        v = self._cookies().get("wmpb_flash")
        if not v:
            return None, False
        return (v[1:], True) if v.startswith("!") else (v, False)

    def _page_dashboard(self):
        st = self._st()
        try:
            q = lambda sql, *a: st.conn.execute(sql, a).fetchone()[0]
            stats = [
                ("待用选题", q("SELECT COUNT(*) FROM topics WHERE status='pending'")),
                ("文章总数", q("SELECT COUNT(*) FROM articles")),
                ("今日生成", q("SELECT COUNT(*) FROM articles WHERE day=?", time.strftime("%Y-%m-%d"))),
                ("发布记录", q("SELECT COUNT(*) FROM publishes")),
            ]
            recent = [dict(r) for r in st.conn.execute(
                "SELECT id,title,category,day,status FROM articles ORDER BY id DESC LIMIT 8")]
        finally:
            st.close()

        tasks = _task_status()
        if tasks:
            rows = "".join(
                '<tr><td>%s</td><td>%s</td><td style="text-align:right">%s</td></tr>'
                % (ui._e(t["label"]), ui._e(t["msg"]),
                   ui._pill({"running": "进行中", "done": "完成", "error": "失败"}[t["status"]],
                            {"running": "generated", "done": "published",
                             "error": "rejected"}[t["status"]]))
                for t in tasks)
            tasks_html = ('<div class="card"><h2>任务</h2><table>%s</table>'
                          '<div class="tip">动作在后台跑，刷新本页看进度。</div></div>' % rows)
        else:
            tasks_html = ""

        flash, err = self._flash()
        body = ui.dashboard(stats, recent) + tasks_html
        return self._send(ui.page("概览", body, active="/",
                                  who=self.cfg.get("admin.user", "admin"),
                                  flash=flash, flash_err=err))

    def _page_topics(self):
        st = self._st()
        try:
            cats = self.cfg.get("categories")
            rows = [dict(r) for r in st.conn.execute(
                "SELECT * FROM topics WHERE status='pending' ORDER BY category, id")]
        finally:
            st.close()
        flash, err = self._flash()
        return self._send(ui.page("选题池", ui.topics_page(cats, rows, None),
                                  active="/topics", who=self.cfg.get("admin.user", "admin"),
                                  flash=flash, flash_err=err))

    def _page_articles(self):
        st = self._st()
        try:
            rows = [dict(r) for r in st.conn.execute(
                "SELECT id,title,category,day,status,body_md FROM articles "
                "ORDER BY id DESC LIMIT 100")]
        finally:
            st.close()
        flash, err = self._flash()
        return self._send(ui.page("文章", ui.articles_page(rows), active="/articles",
                                  who=self.cfg.get("admin.user", "admin"),
                                  flash=flash, flash_err=err))

    def _page_article(self, aid):
        try:
            aid = int(aid)
        except ValueError:
            return self._send("bad id", 400, "text/plain; charset=utf-8")
        st = self._st()
        try:
            a = st.get_article(aid)
        finally:
            st.close()
        if not a:
            return self._send(ui.page("404", '<div class="card">文章不存在</div>'), 404)
        body = ui.article_detail(a, ui.render_article_body(a),
                                 "/articles/%d/paste" % aid)
        flash, err = self._flash()
        return self._send(ui.page(a["title"][:20], body, active="/articles",
                                  who=self.cfg.get("admin.user", "admin"),
                                  flash=flash, flash_err=err))

    def _page_paste(self, aid):
        st = self._st()
        try:
            a = st.get_article(int(aid))
        finally:
            st.close()
        if not a:
            return self._send("not found", 404, "text/plain; charset=utf-8")
        return self._send(render.render_paste_page(a["title"], a["body_html"] or ""))

    def _page_publish(self):
        st = self._st()
        try:
            rows = [dict(r) for r in st.conn.execute(
                "SELECT * FROM publishes ORDER BY id DESC LIMIT 100")]
        finally:
            st.close()
        flash, err = self._flash()
        return self._send(ui.page("发布记录", ui.publish_page(rows), active="/publish",
                                  who=self.cfg.get("admin.user", "admin"),
                                  flash=flash, flash_err=err))


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(cfg_path=None, host=None, port=None):
    cfg = config_mod.load(cfg_path)

    password = cfg.get("admin.password") or os.environ.get("WMPB_ADMIN_PASSWORD") or ""
    if not password:
        raise SystemExit(
            "拒绝启动：后台没有配置密码。\n"
            "请在 config.json 里设置 admin.password，或设置环境变量 WMPB_ADMIN_PASSWORD。\n"
            "这个后台挂在公网上且能触发写稿，没有密码等于把控制权交出去。")
    if not cfg.get("admin.password"):
        cfg._data.setdefault("admin", {})["password"] = password

    st = store_mod.Store(cfg.abs_path("paths.state_db"))
    try:
        secret = _session_secret(cfg, st)
    finally:
        st.close()

    host = host or cfg.get("admin.host", "127.0.0.1")
    port = int(port or cfg.get("admin.port", 8099))

    Handler.cfg = cfg
    Handler.secret = secret

    httpd = ThreadingHTTPServer((host, port), Handler)
    sys_stderr("后台已启动：http://%s:%d/  （监听 %s）" % (host, port, host))
    if host == "0.0.0.0":
        sys_stderr("警告：正在监听 0.0.0.0，请确保外层有 nginx 做 HTTPS 与访问控制。")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sys_stderr("已停止")
    finally:
        httpd.server_close()


def sys_stderr(msg):
    import sys
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()
