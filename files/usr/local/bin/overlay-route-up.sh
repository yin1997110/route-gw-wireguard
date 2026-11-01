#!/bin/bash
# overlay-route-up.sh — 让 LAN 客户端通过本机访问 ZeroTier / Tailscale 网络。
#
# 设计:
#   LAN 客户端继续把 192.168.0.125 当网关；
#   本机把 LAN -> overlay 的流量 MASQUERADE 成 overlay 接口地址；
#   overlay 回程按 conntrack 放行。这样客户端不需要加静态路由。
#
# 使用独立链 OVERLAY_NAT / OVERLAY_FWD，避免 wg-route-up.sh 重启时
# flush ROUTE_GW_NAT / ROUTE_GW_FWD 把 overlay 规则冲掉。
set -u

log() { logger -t overlay-up -- "$*"; echo "[overlay-up] $*"; }

LAN_IF=$(ip route show default | awk '/^default/{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')
if [ -z "${LAN_IF:-}" ]; then
    log "找不到默认路由网卡，退出"
    exit 0
fi
LAN_NET=$(ip -4 route show dev "$LAN_IF" proto kernel scope link 2>/dev/null | awk 'NR==1{print $1}')
if [ -z "${LAN_NET:-}" ]; then
    log "拿不到 $LAN_IF 的 LAN 网段，退出"
    exit 0
fi

# 等 ZeroTier/Tailscale 接口出现（服务启动时可能还没建好）
OVERLAYS=""
for _ in $(seq 1 30); do
    OVERLAYS=$(ip -o link show 2>/dev/null | awk -F': ' '$2 ~ /^(zt|tailscale)/ {print $2}')
    [ -n "$OVERLAYS" ] && break
    sleep 1
done
if [ -z "$OVERLAYS" ]; then
    log "没有发现 zt*/tailscale0 接口，跳过（overlay 未连接时正常）"
    exit 0
fi

# 独立链：不存在则创建，存在则清空
iptables -t nat -n -L OVERLAY_NAT >/dev/null 2>&1 || iptables -t nat -N OVERLAY_NAT
iptables -t nat -C POSTROUTING -j OVERLAY_NAT 2>/dev/null || \
    iptables -t nat -I POSTROUTING 1 -j OVERLAY_NAT
iptables -t nat -F OVERLAY_NAT

iptables -n -L OVERLAY_FWD >/dev/null 2>&1 || iptables -N OVERLAY_FWD
iptables -C FORWARD -j OVERLAY_FWD 2>/dev/null || iptables -I FORWARD 1 -j OVERLAY_FWD
iptables -F OVERLAY_FWD

for iface in $OVERLAYS; do
    iptables -t nat -A OVERLAY_NAT -s "$LAN_NET" ! -d "$LAN_NET" -o "$iface" -j MASQUERADE
    # LAN -> overlay（ROUTE_GW_FWD 也会放行，这里显式写一条便于排查/counter）
    iptables -A OVERLAY_FWD -i "$LAN_IF" -s "$LAN_NET" -o "$iface" -j ACCEPT
    # overlay -> LAN 的回程；如需 overlay 主机主动访问 LAN，可另加 -j ACCEPT
    iptables -A OVERLAY_FWD -i "$iface" -d "$LAN_NET" \
        -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
    log "overlay $iface: $LAN_NET -> $iface (MASQUERADE)"
done

log "overlay NAT/FORWARD 已部署 (LAN=$LAN_NET, ifaces=$OVERLAYS)"
exit 0
