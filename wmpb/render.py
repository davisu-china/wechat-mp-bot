# -*- coding: utf-8 -*-
"""排版渲染：Markdown 子集 -> 全内联样式的 HTML。

为什么不能直接用现成的 Markdown 库：
  公众号编辑器会剥掉 <style> 标签和 class 属性，样式必须内联到每个标签上。

产出两份：
  1. article_html  —— 给微信 draft/add 的 content 字段
  2. preview_page  —— 带手机外框的本地预览页（给人看）
  3. paste_page    —— 纯文章页，打开后 Ctrl+A / Ctrl+C 直接粘进公众号编辑器

第 3 份是「未认证账号走人工发表」这条路的关键：因为样式全内联，
粘过去排版完整保留。
"""

import html as html_mod
import re

from .generate import DEFAULT_THEME

MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
MD_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
MD_CODE_RE = re.compile(r"`([^`]+)`")


def _esc(text):
    return html_mod.escape(text, quote=False)


def _inline(text, theme):
    """行内标记：先转义，再套样式。顺序很重要，否则会破坏标签。"""
    out = _esc(text)
    out = MD_CODE_RE.sub(
        lambda m: '<code style="background:%s;padding:2px 5px;border-radius:3px;'
                  'font-size:0.9em;color:%s;">%s</code>'
                  % (theme["quote_bg"], theme["primary"], m.group(1)), out)
    out = MD_BOLD_RE.sub(
        lambda m: '<strong style="color:%s;font-weight:600;">%s</strong>'
                  % (theme["primary"], m.group(1)), out)
    out = MD_ITALIC_RE.sub(
        lambda m: '<em style="color:%s;">%s</em>' % (theme["muted"], m.group(1)), out)
    return out


def _heading(text, level, theme, index):
    """标题，按 theme.heading_style 渲染四种风格。"""
    size = 20 if level <= 2 else 17
    base = ("font-size:%dpx;font-weight:700;color:%s;line-height:1.5;"
            "margin:28px 0 14px;" % (size, theme["text"]))
    style = theme.get("heading_style", "bar")
    inner = _inline(text, theme)

    if style == "bar":
        wrap = ("border-left:4px solid %s;padding-left:10px;" % theme["primary"])
        return '<h%d style="%s%s">%s</h%d>' % (level, base, wrap, inner, level)
    if style == "underline":
        wrap = ("border-bottom:2px solid %s;padding-bottom:6px;display:inline-block;"
                % theme["primary"])
        return '<h%d style="%s">%s</h%d>' % (level, base, '<span style="%s">%s</span>'
                                             % (wrap, inner), level)
    if style == "numbered":
        num = ('<span style="display:inline-block;width:24px;height:24px;'
               'line-height:24px;text-align:center;border-radius:%dpx;'
               'background:%s;color:#fff;font-size:14px;margin-right:8px;'
               'vertical-align:2px;">%d</span>'
               % (theme["radius"], theme["primary"], index))
        return '<h%d style="%s">%s%s</h%d>' % (level, base, num, inner, level)
    return '<h%d style="%s">%s</h%d>' % (level, base, inner, level)


def _divider(theme):
    d = theme.get("divider", "line")
    if d == "none":
        return ""
    if d == "dots":
        return ('<p style="text-align:center;color:%s;letter-spacing:8px;'
                'margin:24px 0;font-size:12px;">• • •</p>' % theme["muted"])
    if d == "wave":
        return ('<p style="border-top:1px dashed %s;margin:24px 0;"></p>'
                % theme["muted"])
    return ('<p style="border-top:1px solid %s;margin:24px 0;opacity:0.4;"></p>'
            % theme["muted"])


def render_article_html(body_md, theme=None):
    """Markdown 子集 -> 全内联样式的 HTML 片段。"""
    theme = theme or dict(DEFAULT_THEME)
    lines = (body_md or "").replace("\r\n", "\n").split("\n")
    out = []
    buf = []          # 当前段落/列表缓冲
    mode = None       # None | 'p' | 'ul' | 'ol' | 'quote' | 'code'
    heading_index = 0

    def flush():
        if not buf:
            return
        text = "\n".join(buf).strip()
        if not text:
            del buf[:]
            return
        if mode == "ul":
            items = "".join(
                '<li style="margin:6px 0;line-height:inherit;">%s</li>' % _inline(x, theme)
                for x in buf if x.strip()
            )
            out.append('<ul style="padding-left:22px;margin:0 0 %dpx;color:%s;">%s</ul>'
                       % (theme["para_spacing"], theme["text"], items))
        elif mode == "ol":
            items = "".join(
                '<li style="margin:6px 0;line-height:inherit;">%s</li>' % _inline(x, theme)
                for x in buf if x.strip()
            )
            out.append('<ol style="padding-left:22px;margin:0 0 %dpx;color:%s;">%s</ol>'
                       % (theme["para_spacing"], theme["text"], items))
        elif mode == "quote":
            out.append(
                '<blockquote style="margin:%dpx 0;padding:12px 16px;'
                'border-left:3px solid %s;background:%s;color:%s;'
                'border-radius:0 %dpx %dpx 0;">%s</blockquote>'
                % (theme["para_spacing"], theme["quote_border"], theme["quote_bg"],
                   theme["text"], theme["radius"], theme["radius"], _inline(text, theme)))
        elif mode == "code":
            out.append(
                '<pre style="background:%s;padding:14px 16px;border-radius:%dpx;'
                'overflow-x:auto;margin:%dpx 0;"><code style="font-size:13px;'
                'line-height:1.7;color:%s;white-space:pre;">%s</code></pre>'
                % (theme["text"], theme["radius"], theme["para_spacing"],
                   theme["text"], _esc(text)))
        else:
            out.append('<p style="margin:0 0 %dpx;line-height:inherit;">%s</p>'
                       % (theme["para_spacing"], _inline(text, theme)))
        del buf[:]

    in_code = False
    for raw in lines:
        line = raw.rstrip()

        if line.strip().startswith("```"):
            if in_code:
                flush()
                mode = None
                in_code = False
            else:
                flush()
                mode = "code"
                in_code = True
            continue

        if in_code:
            buf.append(line)
            continue

        stripped = line.strip()

        if not stripped:
            flush()
            mode = None
            continue

        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            flush()
            mode = None
            heading_index += 1
            out.append(_heading(m.group(2), len(m.group(1)), theme, heading_index))
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush()
            mode = None
            out.append(_divider(theme))
            continue

        if stripped.startswith("> "):
            if mode != "quote":
                flush()
                mode = "quote"
            buf.append(stripped[2:])
            continue

        m = re.match(r"^[-*+]\s+(.*)$", stripped)
        if m:
            if mode != "ul":
                flush()
                mode = "ul"
            buf.append(m.group(1))
            continue

        m = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if m:
            if mode != "ol":
                flush()
                mode = "ol"
            buf.append(m.group(1))
            continue

        m = MD_IMAGE_RE.match(stripped)
        if m:
            flush()
            mode = None
            out.append('<p style="margin:0 0 %dpx;text-align:center;">'
                       '<img src="%s" style="max-width:100%%;border-radius:%dpx;" /></p>'
                       % (theme["para_spacing"], m.group(2), theme["radius"]))
            continue

        if mode in ("ul", "ol", "quote"):
            flush()
        mode = "p"
        buf.append(stripped)

    flush()

    return ('<section style="font-size:%dpx;line-height:%s;color:%s;'
            'letter-spacing:%spx;text-align:justify;">%s</section>'
            % (theme["font_size"], theme["line_height"], theme["text"],
               theme["letter_spacing"], "".join(out)))


def render_paste_page(title, article_html):
    """纯文章页：打开后 Ctrl+A / Ctrl+C 可直接粘进公众号编辑器。"""
    return (
        '<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="utf-8">\n'
        '<title>%s</title>\n'
        '<style>body{margin:0;padding:24px 16px;background:#fff;'
        'font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;}'
        '#doc{max-width:677px;margin:0 auto;}</style>\n'
        '</head><body>\n'
        '<div id="doc">\n<h1 style="font-size:22px;font-weight:700;'
        'margin:0 0 20px;line-height:1.4;color:#222;">%s</h1>\n%s\n</div>\n'
        '</body></html>' % (_esc(title), _esc(title), article_html)
    )


def render_preview_page(title, digest, article_html, theme, meta=None):
    """带手机外框的预览页，仅用于人眼查看效果。"""
    meta = meta or {}
    meta_rows = "".join(
        '<div style="font-size:12px;color:#8A8F99;margin-top:4px;">'
        '<b style="color:#5C6577;">%s</b> %s</div>' % (_esc(k), _esc(str(v)))
        for k, v in meta.items()
    )
    swatches = "".join(
        '<span title="%s" style="display:inline-block;width:22px;height:22px;'
        'border-radius:4px;background:%s;border:1px solid rgba(0,0,0,.1);'
        'margin-right:6px;vertical-align:middle;"></span>' % (k, theme.get(k, "#fff"))
        for k in ("primary", "accent", "text", "muted", "quote_bg", "quote_border")
    )
    return (
        '<!DOCTYPE html>\n<html lang="zh-CN"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        '<title>预览 · %s</title>\n'
        '<style>*{box-sizing:border-box}body{margin:0;background:#EDEFF2;'
        'font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;'
        'padding:32px 16px;}\n'
        '.phone{max-width:375px;margin:0 auto;background:#fff;border-radius:18px;'
        'box-shadow:0 10px 40px rgba(0,0,0,.13);overflow:hidden;}\n'
        '.bar{background:#FAFAFB;border-bottom:1px solid #ECEEF1;padding:10px 16px;'
        'font-size:12px;color:#8A8F99;text-align:center;}\n'
        '.body{padding:20px 18px 40px;}\n'
        '</style></head><body>\n'
        '<div class="phone">\n'
        '<div class="bar">微信预览 · 375px</div>\n'
        '<div class="body">\n'
        '<h1 style="font-size:21px;font-weight:700;line-height:1.4;margin:0 0 10px;'
        'color:#1A1A1A;">%s</h1>\n'
        '<p style="font-size:13px;color:#8A8F99;margin:0 0 20px;line-height:1.6;">%s</p>\n'
        '%s\n'
        '</div></div>\n'
        '<div style="max-width:375px;margin:20px auto 0;background:#fff;'
        'border-radius:12px;padding:16px;box-shadow:0 4px 16px rgba(0,0,0,.06);">\n'
        '<div style="font-size:11px;letter-spacing:.1em;color:#8A8F99;'
        'text-transform:uppercase;margin-bottom:10px;">AI 生成的样式主题</div>\n'
        '<div style="margin-bottom:10px;">%s</div>\n'
        '<div style="font-size:12px;color:#5C6577;line-height:1.8;">'
        '字号 %s px · 行高 %s · 标题样式 %s · 分割线 %s</div>\n'
        '%s\n'
        '</div>\n'
        '</body></html>'
        % (_esc(title), _esc(title), _esc(digest), article_html, swatches,
           theme.get("font_size"), theme.get("line_height"),
           _esc(str(theme.get("heading_style"))), _esc(str(theme.get("divider"))),
           meta_rows)
    )
