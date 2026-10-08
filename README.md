# wechat-mp-bot
每日生成微信公众号推文

选题 → 生成 → 排版 → 审核 → 发布 的全自动流水线。每日定时产出成稿，推送到飞书确认后自动发布；账号权限不足时自动降级为「存草稿 + 人工发表」。

## 文档

- 产品技术方案 → https://davisu-china.github.io/wechat-mp-bot/

## 运行环境

纯 Python 3.6 标准库实现，**零第三方依赖**，无需 pip install。

## 快速开始

```bash
cp config.example.json config.json   # 填入 AppID / AppSecret / 模型 Key
python3.6 run.py preview             # 只生成 + 出本地预览，不发布
python3.6 run.py run                 # 跑全流程
```

## 部署前必做

1. 把本机出口 IP `111.228.14.136` 加入公众号后台 IP 白名单，否则报 `40164`
2. 确认公众号认证状态 —— 未认证账号无发布接口权限（`48001`），只能走草稿模式
