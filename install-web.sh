#!/bin/bash
# install-web.sh — 在 LXC 201 (router) 内以 root 执行：安装/升级分流网关管理面板
#
# 用法:
#   bash /opt/route-gw-deploy/install-web.sh                        # 首次安装，自动生成管理员密码并打印
#   ADMIN_PASSWORD='你的密码' bash /opt/route-gw-deploy/install-web.sh  # 指定密码(首装与改密都生效)
#   GW_PANEL_PORT=9000 bash /opt/route-gw-deploy/install-web.sh      # 换监听端口(默认 8080)
#
# 幂等: 可反复执行用于升级。/opt/gw-admin/data 下的节点池/规则/事件/账号不会被覆盖。
set -euo pipefail

BASE="$(cd "$(dirname "$0")" && pwd)"
WEB="$BASE/web"
APP="/opt/gw-admin"
DATA="$APP/data"
PORT="${GW_PANEL_PORT:-8080}"

[ "$(id -u)" = 0 ] || { echo "请用 root 执行"; exit 1; }
[ -f "$WEB/server/gw_server.py" ] || { echo "找不到 $WEB/server/gw_server.py"; exit 1; }

echo "[1/6] 依赖检查"
# 面板是纯 Python 标准库实现，只要 python3 在即可；CT201 已自带 3.12
if ! command -v python3 >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq && apt-get install -y -qq python3
fi
python3 -V
command -v curl >/dev/null 2>&1 || { export DEBIAN_FRONTEND=noninteractive; apt-get install -y -qq curl; }

echo "[2/6] 目录与备份"
install -d "$APP" "$DATA"
if [ -f "$APP/gw_server.py" ]; then
    cp -a "$APP/gw_server.py" "$APP/gw_server.py.bak"
    echo "  旧版后端已备份为 gw_server.py.bak"
fi

echo "[3/6] 投放后端"
sed -i 's/\r$//' "$WEB/server/gw_server.py"
install -m 644 "$WEB/server/gw_server.py" "$APP/gw_server.py"
python3 -m py_compile "$APP/gw_server.py"
echo "  后端: $APP/gw_server.py ($(wc -c < "$APP/gw_server.py") bytes)"

echo "[4/6] 投放前端静态产物"
# 前端产物就是 vite 的构建输出 web/app/dist，随包分发，201 上没有 Node 不用重新构建
DIST="$WEB/app/dist"
if [ -d "$DIST" ] && [ -f "$DIST/index.html" ]; then
    rm -rf "$APP/dist.new"
    cp -a "$DIST" "$APP/dist.new"
    rm -rf "$APP/dist.old"
    [ -d "$APP/dist" ] && mv "$APP/dist" "$APP/dist.old"
    mv "$APP/dist.new" "$APP/dist"
    rm -rf "$APP/dist.old"
    echo "  前端: $APP/dist ($(du -sh "$APP/dist" | cut -f1))"
else
    [ -d "$APP/dist" ] && echo "  保留已有前端产物 $APP/dist" \
        || { echo "  缺 web/app/dist，且本机无旧产物：先在开发机 web/app 下 npx vite build 再打包"; exit 1; }
fi

echo "[5/6] systemd 常驻"
sed -i 's/\r$//' "$WEB/gw-admin.service"
install -m 644 "$WEB/gw-admin.service" /etc/systemd/system/gw-admin.service
# 后端读的是 GW_PORT(默认 8080)。换端口必须同时喂给服务和自检，否则自检去 curl 一个没人听的口。
if [ -n "${GW_PANEL_PORT:-}" ] && [ "$GW_PANEL_PORT" != "8080" ]; then
    install -d /etc/systemd/system/gw-admin.service.d
    printf '[Service]\nEnvironment=GW_PORT=%s\n' "$GW_PANEL_PORT" \
        > /etc/systemd/system/gw-admin.service.d/port.conf
    echo "  监听端口改为 $GW_PANEL_PORT(drop-in: gw-admin.service.d/port.conf)"
else
    rm -rf /etc/systemd/system/gw-admin.service.d
fi
systemctl daemon-reload

# 端口占用检查：只有"非本服务"的残留进程才需要手动杀
if ss -lnt "sport = :$PORT" 2>/dev/null | grep -q LISTEN; then
    if systemctl is-active --quiet gw-admin 2>/dev/null; then
        echo "  端口 $PORT 由 gw-admin.service 持有，稍后直接 restart"
    else
        echo "  端口 $PORT 被残留进程占用，先停掉"
        pkill -f 'gw_server.py' 2>/dev/null || true
        sleep 1
    fi
fi

echo "[6/6] 管理员账号与启动"
if [ ! -f "$DATA/credentials.json" ] || [ -n "${ADMIN_PASSWORD:-}" ]; then
    PW="${ADMIN_PASSWORD:-}"
    if [ -z "$PW" ]; then
        PW="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)"
        echo "  已随机生成管理员密码(仅此一次，请立即记录)"
    fi
    python3 "$APP/gw_server.py" --set-password admin "$PW"
    [ -f "$DATA/INITIAL_PASSWORD.txt" ] && rm -f "$DATA/INITIAL_PASSWORD.txt"
    chmod 600 "$DATA/credentials.json"
    [ "${ADMIN_PASSWORD:-}" = "" ] && echo "  账号 admin / 密码 $PW" || echo "  账号 admin 密码已按 ADMIN_PASSWORD 设置"
else
    echo "  已存在账号文件，跳过(改密用 --set-password 或登录后在「系统设置」修改)"
fi

systemctl enable gw-admin >/dev/null 2>&1
systemctl restart gw-admin
sleep 6
systemctl --no-pager -l status gw-admin | head -8

echo
echo "===== 自检 ====="
# 用两个"无需登录也返回"的探针：静态首页 + /api/user/info。
# /api/system/info 之类接口在未登录时返回的是 HTTP 200 + code 401，curl -f 不会失败，
# 拿它做健康检查等于什么都没测。
curl -fsS "http://127.0.0.1:$PORT/" | grep -q '<div id="app">' \
    && echo "  首页 OK: 静态产物已就位" || echo "  首页异常(检查 $APP/dist)"
curl -fsS "http://127.0.0.1:$PORT/api/user/info" | grep -q '"code"' \
    && echo "  API OK: 面板已在 :$PORT 提供接口" || echo "  API 无响应"
curl -fsS "http://127.0.0.1:$PORT/api/user/info" >/dev/null \
    || { echo "  自检失败，最近日志:"; journalctl -u gw-admin -n 30 --no-pager; exit 1; }

IP="$(ip -o -4 addr show scope global 2>/dev/null | awk '$2!="wg0"{print $4; exit}' | cut -d/ -f1)"
echo
echo "访问地址: http://${IP:-<网关IP>}:$PORT   账号: admin"
echo "日志: journalctl -u gw-admin -f     重启: systemctl restart gw-admin"
