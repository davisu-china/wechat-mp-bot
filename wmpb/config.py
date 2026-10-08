# -*- coding: utf-8 -*-
"""配置加载。

真实配置放 config.json（不入库），仓库只留 config.example.json。
密钥一律用 ${ENV_VAR} 占位，运行时从环境变量替换，绝不硬编码进配置。
"""

import copy
import json
import os
import re

_ENV_RE = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')

DEFAULTS = {
    "wechat": {
        "appid": "",
        "appsecret": "",
        # auto: 探测权限后自动选；free/mass/draft: 强制指定
        "publisher": "auto",
        "author": "",
    },
    "llm": {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "api_key": "",
        "timeout": 120,
        "max_tokens": 8000,
        # DeepSeek V4 默认开思考模式，写推文不需要；开着会多烧约 65% 输出 token
        # 且会挤占 max_tokens 导致正文为空。默认关闭。
        "thinking": False,
    },
    "image": {
        "enabled": False,
        "provider": "dashscope",
        "base_url": "https://dashscope.aliyuncs.com",
        "model": "wan2.1-t2i-turbo",
        "api_key": "",
        # 封面尺寸。微信封面推荐 900x383（约 2.35:1），
        # 万相不支持任意比例，故取接近的宽幅，由微信侧裁剪。
        "cover_size": "1280*544",
        "timeout": 180,
    },
    "review": {
        # hold: 超时不动作（默认，最安全）| draft: 超时存草稿 | publish: 超时直接发
        "timeout_action": "hold",
    },
    "schedule": {
        "generate_at": "07:00",
        "publish_at": "08:00",
    },
    "render": {
        # 每篇由模型现场生成样式主题（AI 生成的 UI）
        "ai_theme": True,
        "fallback_theme": "default",
    },
    "collect": {
        # 留空表示启用 sources.py 里全部已实测可达的源
        "sources": [],
        # 每次喂给模型多少条候选
        "batch": 80,
        # 抓取每个源多少条
        "limit": 40,
        # 每个栏目最多挑多少条选题入池
        "per_category": 6,
    },
    "categories": [],
    "paths": {
        "workspace": "workspace",
        "state_db": "state.db",
        "topic_pool": "workspace/topics.json",
    },
}


def _expand(value):
    """递归替换 ${VAR} 为环境变量值。未设置的变量替换为空串。"""
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return dict((k, _expand(v)) for k, v in value.items())
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def _merge(base, override):
    """深度合并：override 覆盖 base，字典递归，其余类型直接替换。"""
    out = copy.deepcopy(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config(object):
    """支持点号路径读取的配置对象：cfg.get('llm.model', 'x')"""

    def __init__(self, data, path=None):
        self._data = data
        self.path = path

    def get(self, dotted, default=None):
        node = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def __getitem__(self, key):
        return self._data[key]

    def as_dict(self):
        return copy.deepcopy(self._data)

    def abs_path(self, dotted, default=None):
        """取路径类配置，转为相对配置文件的绝对路径。"""
        raw = self.get(dotted, default)
        if not raw:
            return raw
        if os.path.isabs(raw):
            return raw
        base = os.path.dirname(os.path.abspath(self.path)) if self.path else os.getcwd()
        return os.path.join(base, raw)


def load(path=None):
    """加载配置。path 为空时按 config.json -> config.example.json 顺序查找。"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [path] if path else [
        os.path.join(base, "config.json"),
        os.path.join(base, "config.example.json"),
    ]
    chosen = None
    for c in candidates:
        if c and os.path.exists(c):
            chosen = c
            break
    if not chosen:
        raise IOError("找不到配置文件，请先 cp config.example.json config.json")

    with open(chosen, "r") as f:
        user = json.load(f)

    merged = _expand(_merge(DEFAULTS, user))
    cfg = Config(merged, path=chosen)
    _validate(cfg)
    return cfg


def _validate(cfg):
    if not cfg.get("categories"):
        raise ValueError("配置里至少需要一个 categories 栏目")

    provider = cfg.get("llm.provider")
    if provider == "deepseek" and not cfg.get("llm.api_key"):
        raise ValueError("缺少 LLM api_key（可用 ${DEEPSEEK_API_KEY} 从环境变量注入）")

    # 图片 key 缺失不算致命：采集与写稿不依赖它，关掉图片生成继续跑即可。
    if cfg.get("image.enabled") and not cfg.get("image.api_key"):
        import sys
        sys.stderr.write(
            "[warn] 未配置 image.api_key，已自动关闭封面图生成。"
            "如需封面图，请设置 ${DASHSCOPE_API_KEY}。\n")
        cfg._data["image"]["enabled"] = False
