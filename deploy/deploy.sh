#!/usr/bin/env bash
#
# 把 wechat-mp-bot 后台部署到京东云（就是本机）。
#
# 前置（必须人工先做完，脚本不碰这两件）：
#   1. Cloudflare 加一条 DNS：wmpb.jianjiange.site → 本机（A 记录，或与
#      其它子域一致的 CNAME）。证书签不出来就是因为这步没做。
#   2. 配置好后台密码：在 config.json 的 admin.password，或设
#      WMPB_ADMIN_PASSWORD 环境变量。没密码后台会拒绝启动。
#
# 用法（在仓库根目录）：
#   sudo deploy/deploy.sh
#
# 可覆盖：DIR DOMAIN PORT NGINX_CONF NGINX_CONTAINER CERTBOT_DIR LE_EMAIL
set -euo pipefail

DIR="${DIR:-/opt/wechat-mp-bot}"
DOMAIN="${DOMAIN:-wmpb.jianjiange.site}"
PORT="${PORT:-8099}"
BIND="${BIND:-172.17.0.1}"
NGINX_CONF="${NGINX_CONF:-/opt/jianjian/deploy/nginx/nginx.conf}"
NGINX_CONTAINER="${NGINX_CONTAINER:-jianjian-nginx}"
CERTBOT_DIR="${CERTBOT_DIR:-/opt/jianjian/deploy/certbot}"
LE_EMAIL="${LE_EMAIL:-898168605@qq.com}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log()  { printf '\n\033[36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
[ "$(id -u)" = "0" ] || die "需要 root：sudo $0"

# ------------------------------------------------------------------ 1. 同步源码
log "同步源码 → $DIR"
mkdir -p "$DIR"
rsync -a --delete \
  --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude 'workspace' --exclude 'state.db' --exclude 'deploy/.env' \
  --exclude 'index.html' \
  "$REPO/" "$DIR/"
# state.db 与 workspace 在部署目录里单独保留，rsync 的 --delete 不会碰它们
mkdir -p "$DIR/workspace"
[ -f "$DIR/config.json" ] || warn "部署目录还没有 config.json，后台会因为缺密码拒绝启动"

# ------------------------------------------------------------------ 2. 起服务
log "启动后台服务（$BIND:$PORT）"
cat > /etc/systemd/system/wmpb-admin.service <<UNIT
[Unit]
Description=wechat-mp-bot admin
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$DIR
EnvironmentFile=-$DIR/deploy/.env
ExecStart=/usr/bin/python3.6 $DIR/run.py admin --host $BIND --port $PORT
Restart=always
RestartSec=5
StandardOutput=append:$DIR/workspace/admin.log
StandardError=append:$DIR/workspace/admin.log

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable wmpb-admin >/dev/null
systemctl restart wmpb-admin
sleep 2
systemctl is-active --quiet wmpb-admin || { journalctl -u wmpb-admin -n 30 --no-pager; die "服务没起来"; }
curl -fsS -o /dev/null "http://$BIND:$PORT/login" || die "本机探活失败"
echo "  ✓ 服务在跑，本机 /login 可达"

# ------------------------------------------------------------------ 3. 证书
log "申请证书 $DOMAIN"
mkdir -p "$CERTBOT_DIR/conf" "$CERTBOT_DIR/www"
if [ -d "$CERTBOT_DIR/conf/live/$DOMAIN" ]; then
  echo "  ✓ 证书已存在，跳过"
elif ! getent hosts "$DOMAIN" >/dev/null; then
  warn "DNS 还没解析到 $DOMAIN —— 先加 Cloudflare 记录，再重跑本脚本"
else
  docker run --rm \
    -v "$CERTBOT_DIR/conf:/etc/letsencrypt" \
    -v "$CERTBOT_DIR/www:/var/www/certbot" \
    certbot/certbot certonly --webroot -w /var/www/certbot \
    -d "$DOMAIN" --email "$LE_EMAIL" --agree-tos --non-interactive
  echo "  ✓ 证书已签发"
fi

# ------------------------------------------------------------------ 4. vhost
log "合并 vhost 到共享 nginx"
[ -d "$CERTBOT_DIR/conf/live/$DOMAIN" ] || die "没有证书，不合并 vhost（引用了证书文件，合进去 nginx -t 会失败，reload 会弄挂所有站）"

if grep -q "server_name $DOMAIN;" "$NGINX_CONF"; then
  echo "  ✓ vhost 已存在，跳过"
else
  cp "$NGINX_CONF" "$NGINX_CONF.bak.wmpb.$(date +%Y%m%d-%H%M%S)"
  # 关键：原地覆盖，不能 sed -i（会换 inode，容器读不到）
  { cat "$NGINX_CONF"; echo; cat "$REPO/deploy/nginx/wmpb.conf"; } > /tmp/wmpb.nginx.new
  cat /tmp/wmpb.nginx.new > "$NGINX_CONF"
  echo "  ✓ 已追加 vhost（原文件已备份）"
fi

log "校验并 reload"
docker exec "$NGINX_CONTAINER" nginx -t || {
  warn "nginx -t 失败，回滚"
  cat "$(ls -t "$NGINX_CONF".bak.wmpb.* | head -1)" > "$NGINX_CONF"
  docker exec "$NGINX_CONTAINER" nginx -t && docker exec "$NGINX_CONTAINER" nginx -s reload
  die "已回滚，排查后再试"
}
docker exec "$NGINX_CONTAINER" nginx -s reload
echo "  ✓ nginx 已 reload"

# ------------------------------------------------------------------ 5. 验收
log "验收"
sleep 1
code=$(curl -s -o /dev/null -w '%{http_code}' "https://$DOMAIN/login" || true)
echo "  https://$DOMAIN/login -> $code"
[ "$code" = "200" ] && echo "  ✓ 部署完成" || warn "返回 $code，检查 DNS / 证书 / vhost"
echo
echo "后台地址： https://$DOMAIN/"
echo "日志：     journalctl -u wmpb-admin -f   或  $DIR/workspace/admin.log"
