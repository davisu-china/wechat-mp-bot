# -*- coding: utf-8 -*-
"""HTTP 客户端：urllib 封装。

业务层不允许直接调用 urllib —— 所有外部请求（微信 / DeepSeek / 万相）都走这里，
统一处理超时、重试、JSON 解析和错误提取。

纯标准库实现，不依赖 requests。
"""

import json
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_TIMEOUT = 15
DEFAULT_RETRIES = 3
# 这些状态码值得重试；4xx 里的客户端错误不重试
RETRY_STATUSES = (408, 429, 500, 502, 503, 504)


class HttpError(Exception):
    def __init__(self, message, status=None, body=None, url=None):
        Exception.__init__(self, message)
        self.status = status
        self.body = body
        self.url = url


def request(method, url, headers=None, body=None, timeout=DEFAULT_TIMEOUT,
            retries=DEFAULT_RETRIES, retry_statuses=RETRY_STATUSES):
    """发起请求，返回 (status, text)。网络错误与可重试状态码按指数退避重试。"""
    headers = dict(headers or {})
    last_err = None

    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, method=method)
        for k, v in headers.items():
            req.add_header(k, v)

        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            try:
                return resp.getcode(), resp.read().decode("utf-8", "replace")
            finally:
                resp.close()

        except urllib.error.HTTPError as e:
            text = ""
            try:
                text = e.read().decode("utf-8", "replace")
            except Exception:
                pass
            if e.code in retry_statuses and attempt < retries:
                last_err = HttpError("HTTP %s" % e.code, e.code, text, url)
                time.sleep(2 ** attempt)
                continue
            raise HttpError("HTTP %s: %s" % (e.code, text[:300]), e.code, text, url)

        except (urllib.error.URLError, OSError) as e:
            # 网络层错误（DNS / 连接超时 / 被拒）；IP 白名单不通也会落在这里
            last_err = HttpError("网络错误: %s" % e, None, None, url)
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue

    raise last_err


def get_json(url, headers=None, timeout=DEFAULT_TIMEOUT, retries=DEFAULT_RETRIES):
    status, text = request("GET", url, headers=headers, timeout=timeout, retries=retries)
    return _parse_json(text, url, status)


def post_json(url, payload, headers=None, timeout=DEFAULT_TIMEOUT, retries=DEFAULT_RETRIES):
    h = {"Content-Type": "application/json"}
    h.update(headers or {})
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    status, text = request("POST", url, headers=h, body=body, timeout=timeout, retries=retries)
    return _parse_json(text, url, status)


def _parse_json(text, url, status):
    try:
        return json.loads(text)
    except ValueError:
        raise HttpError("响应不是合法 JSON（HTTP %s）: %s" % (status, text[:300]),
                        status, text, url)


def post_multipart(url, fields=None, files=None, headers=None,
                   timeout=60, retries=2):
    """multipart/form-data 上传。

    urllib 不直接支持 multipart，这里手写 body。
    微信素材上传（media/uploadimg、material/add_material）依赖它。
    files: [(field_name, filename, content_bytes), ...]
    """
    boundary = "----wmpb" + uuid.uuid4().hex
    buf = bytearray()

    for k, v in (fields or {}).items():
        buf.extend(("--%s\r\n" % boundary).encode("utf-8"))
        buf.extend(('Content-Disposition: form-data; name="%s"\r\n\r\n' % k).encode("utf-8"))
        buf.extend(str(v).encode("utf-8"))
        buf.extend(b"\r\n")

    for field_name, filename, content in (files or []):
        buf.extend(("--%s\r\n" % boundary).encode("utf-8"))
        buf.extend(
            ('Content-Disposition: form-data; name="%s"; filename="%s"\r\n'
             % (field_name, filename)).encode("utf-8")
        )
        buf.extend(b"Content-Type: application/octet-stream\r\n\r\n")
        buf.extend(content)
        buf.extend(b"\r\n")

    buf.extend(("--%s--\r\n" % boundary).encode("utf-8"))

    h = {"Content-Type": "multipart/form-data; boundary=%s" % boundary}
    h.update(headers or {})
    status, text = request("POST", url, headers=h, body=bytes(buf),
                           timeout=timeout, retries=retries)
    return _parse_json(text, url, status)


def build_url(base, path, query=None):
    url = base.rstrip("/") + "/" + path.lstrip("/")
    if query:
        url += "?" + urllib.parse.urlencode(query)
    return url
