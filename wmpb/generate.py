# -*- coding: utf-8 -*-
"""内容生成：调用 DeepSeek 产出文章 + 样式主题。

关键设计：一次调用同时产出【文章内容】和【样式主题】。
  - 内容：title / digest / body_md
  - 样式主题：一组颜色与排版参数，由模型按内容气质现场决定

为什么不让模型直接吐 HTML：公众号编辑器不认外部 CSS 与 <style> 标签，
模型一旦生成越界的结构，整篇排版就废了。让模型只产出【样式参数】，
由渲染器套进安全的 HTML 骨架 —— 视觉上篇篇不同（AI 生成），
结构上永远可控。
"""

import hashlib
import json
import re

from . import http

# DeepSeek 定价（USD / 百万 token），用于成本估算
PRICING = {
    "deepseek-v4-flash": {"in": 0.14, "out": 0.28},
    "deepseek-v4-pro": {"in": 0.435, "out": 0.87},
}

DEFAULT_THEME = {
    "primary": "#2C4A8C",
    "accent": "#C8862A",
    "text": "#333333",
    "muted": "#8A8F99",
    "quote_bg": "#F5F6F8",
    "quote_border": "#2C4A8C",
    "font_size": 16,
    "line_height": 1.8,
    "letter_spacing": 0.5,
    "para_spacing": 16,
    "radius": 6,
    "heading_style": "bar",
    "divider": "line",
}

SYSTEM_PROMPT = """你是一位资深的微信公众号主编，负责一个面向技术从业者的公众号。

你的写作要求：
- 标题：具体、有信息量，不标题党，不超过 30 字
- 摘要：一句话说清文章价值，不超过 60 字
- 正文：800-1500 字，Markdown 格式（只允许使用 ## 小标题、**加粗**、> 引用、- 列表、段落）
- 语气自然，像跟同行聊天，不用「赋能」「闭环」「抓手」这类词
- 有具体观点和例子，不写空话
- 正文内不要出现任何图片语法

你还要为这篇文章设计一套视觉样式（会渲染成公众号排版），
根据文章气质决定配色：严肃内容用冷色，轻松内容可以暖一些。
颜色必须是十六进制色值，正文色要保证在白色背景上可读。

只输出 JSON，不要输出任何解释文字、不要用 ``` 包裹。格式：
{
  "title": "文章标题",
  "digest": "摘要",
  "body_md": "正文 Markdown",
  "cover_prompt": "用于文生图模型的封面图提示词，中文，描述画面内容与风格，不要出现文字",
  "theme": {
    "primary": "#十六进制主色",
    "accent": "#十六进制点缀色",
    "text": "#正文色",
    "muted": "#次要文字色",
    "quote_bg": "#引用块背景色",
    "quote_border": "#引用块左边框色",
    "font_size": 16,
    "line_height": 1.8,
    "letter_spacing": 0.5,
    "para_spacing": 16,
    "radius": 6,
    "heading_style": "bar",
    "divider": "line"
  }
}

其中 heading_style 可选：bar（左侧竖条）、underline（下划线）、plain（无装饰）、numbered（编号）
divider 可选：line（细线）、dots（圆点）、wave（波浪）、none（无）"""


def _digest_prompt(prompt):
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


class LLMClient(object):
    def __init__(self, cfg):
        self.cfg = cfg
        self.base_url = cfg.get("llm.base_url")
        self.model = cfg.get("llm.model")
        self.api_key = cfg.get("llm.api_key")
        self.timeout = int(cfg.get("llm.timeout", 120))

    def chat(self, messages, temperature=0.8, max_tokens=None, thinking=None):
        """OpenAI 兼容的 chat/completions。返回 (content, usage)。

        关于 thinking：DeepSeek V4 默认开启思考模式，会先产出一大段
        reasoning_content（实测一篇推文能烧掉 3400+ 推理 token），
        这些 token 按输出价计费，且会挤占 max_tokens 导致正文被截断甚至为空。
        写推文不需要长链推理，默认关闭。实测有效的写法只有
        {"thinking": {"type": "disabled"}}，enable_thinking / chat_template_kwargs 均无效。
        """
        url = http.build_url(self.base_url, "/chat/completions")
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        payload["max_tokens"] = int(max_tokens or self.cfg.get("llm.max_tokens", 8000))

        use_thinking = self.cfg.get("llm.thinking", False) if thinking is None else thinking
        if not use_thinking:
            payload["thinking"] = {"type": "disabled"}

        data = http.post_json(
            url, payload,
            headers={"Authorization": "Bearer %s" % self.api_key},
            timeout=self.timeout, retries=2,
        )
        if "choices" not in data:
            raise http.HttpError("模型返回异常: %s" % json.dumps(data, ensure_ascii=False)[:300])
        content = data["choices"][0]["message"].get("content") or ""
        return content, data.get("usage", {})

    def estimate_cost(self, usage):
        p = PRICING.get(self.model)
        if not p or not usage:
            return 0.0
        return (usage.get("prompt_tokens", 0) * p["in"]
                + usage.get("completion_tokens", 0) * p["out"]) / 1000000.0


def _extract_json(text):
    """从模型输出里抠出 JSON。容忍 ```json 包裹和前后多余文字。"""
    if not text:
        raise ValueError("模型输出为空")
    t = text.strip()

    fence = re.search(r"```(?:json)?\s*(.+?)```", t, re.S)
    if fence:
        t = fence.group(1).strip()

    try:
        return json.loads(t)
    except ValueError:
        pass

    start, end = t.find("{"), t.rfind("}")
    if start >= 0 and end > start:
        return json.loads(t[start:end + 1])
    raise ValueError("无法从模型输出中解析 JSON: %s" % t[:200])


def _normalize_theme(raw):
    """把模型给的样式参数收敛到安全范围，防止离谱值把排版搞坏。"""
    theme = dict(DEFAULT_THEME)
    if not isinstance(raw, dict):
        return theme

    color_keys = ["primary", "accent", "text", "muted", "quote_bg", "quote_border"]
    for k in color_keys:
        v = raw.get(k)
        if isinstance(v, str) and re.match(r"^#[0-9A-Fa-f]{6}$", v.strip()):
            theme[k] = v.strip()

    def clamp(key, lo, hi, cast=float):
        try:
            v = cast(raw.get(key, theme[key]))
        except (TypeError, ValueError):
            return
        theme[key] = min(hi, max(lo, v))

    clamp("font_size", 14, 20, int)
    clamp("line_height", 1.4, 2.4)
    clamp("letter_spacing", 0, 2)
    clamp("para_spacing", 8, 32, int)
    clamp("radius", 0, 16, int)

    if raw.get("heading_style") in ("bar", "underline", "plain", "numbered"):
        theme["heading_style"] = raw["heading_style"]
    if raw.get("divider") in ("line", "dots", "wave", "none"):
        theme["divider"] = raw["divider"]

    return theme


def generate_article(cfg, store, category, topic, recent_titles=None):
    """生成一篇文章。返回 dict，含 title/digest/body_md/cover_prompt/theme。"""
    client = LLMClient(cfg)
    recent = recent_titles or []

    lines = [
        "栏目：%s" % category.get("name", category.get("key", "")),
        "栏目语气倾向：%s" % category.get("tone", "自然、专业"),
        "今日选题：%s" % (topic.get("title", "") if topic else "（自由发挥，选一个符合栏目定位的题目）"),
    ]
    if topic and topic.get("hint"):
        lines.append("选题补充说明：%s" % topic["hint"])
    if recent:
        lines.append("近期已发过的标题（请避免重复或雷同）：%s" % "、".join(recent[:15]))

    user_prompt = "\n".join(lines)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    content, usage = client.chat(messages)

    # 兜底：模型偶尔返回空正文（多为推理 token 挤占了 max_tokens）。
    # 关掉思考 + 放大预算重试一次，仍为空才报错。
    if not (content or "").strip():
        rt = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
        content, usage = client.chat(messages, thinking=False, max_tokens=16000)
        if not (content or "").strip():
            raise ValueError(
                "模型返回空正文（推理 token=%s，输出上限=%s）。"
                "通常是思考模式挤占了 max_tokens，请提高 llm.max_tokens 或确认 thinking 已关闭。"
                % (rt, cfg.get("llm.max_tokens")))

    data = _extract_json(content)
    article = {
        "title": (data.get("title") or "").strip(),
        "digest": (data.get("digest") or "").strip(),
        "body_md": (data.get("body_md") or "").strip(),
        "cover_prompt": (data.get("cover_prompt") or "").strip(),
        "theme": _normalize_theme(data.get("theme")),
        "_raw": content,
        "_usage": usage,
        "_cost": client.estimate_cost(usage),
    }

    if not article["title"] or not article["body_md"]:
        raise ValueError("模型没有产出有效内容：%s" % content[:200])

    store.log_llm(None, "article", client.model, _digest_prompt(user_prompt),
                  content, article["_cost"])
    return article


def generate_topics(cfg, category, n=5, recent_titles=None):
    """选题池空了时，让模型现场出一批候选选题。"""
    client = LLMClient(cfg)
    recent = recent_titles or []
    prompt = (
        "栏目：%s\n栏目语气倾向：%s\n"
        "请为这个公众号栏目提出 %d 个具体、可写的选题，每个不超过 30 字。\n"
        "%s\n"
        "只输出 JSON 数组，例如 [\"选题一\", \"选题二\"]，不要任何解释。"
        % (category.get("name", ""), category.get("tone", "自然、专业"), n,
           ("已发过的标题（避免重复）：%s" % "、".join(recent[:15])) if recent else "")
    )
    content, _ = client.chat([
        {"role": "system", "content": "你是公众号选题编辑，只输出 JSON 数组。"},
        {"role": "user", "content": prompt},
    ], temperature=1.0)
    data = _extract_json(content)
    if isinstance(data, dict):
        data = data.get("topics", [])
    return [str(x).strip() for x in data if str(x).strip()][:n]
