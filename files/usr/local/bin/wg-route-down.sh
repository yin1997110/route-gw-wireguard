#!/bin/bash
# wg-route-down.sh — WireGuard PostDown 钩子：清理分流策略路由 (LXC 201)
#
# 相比旧版修复: ENDPOINT 从 wg0.conf 静态解析（PostDown 时可能已无握手记录，
# 旧版依赖 `wg show endpoints` 会漏删 anti-loop 路由）；WAN_GW/WAN_IF 自动探测。
set -u

WG_CONF="/etc/wireguard/wg0.conf"
CHINA_LIST="/etc/china_ip_list.txt"

WAN_GW=$(ip route show default | awk '/^default/{print $3; exit}')
ENDPOINT=$(awk -F'[ =:]' '/^Endpoint/{print $4; exit}' "$WG_CONF")

logger -t wg-down "清理 WG 分流路由 (endpoint=$ENDPOINT gw=$WAN_GW)"

# NAT/FORWARD 规则保留不删（对直连模式无害，重启隧道时幂等复用）

if [ -f "$CHINA_LIST" ] && [ -n "$WAN_GW" ]; then
    while IFS= read -r cidr; do
        [ -z "$cidr" ] && continue
        ip route del "$cidr" via "$WAN_GW" 2>/dev/null
    done < "$CHINA_LIST"
fi

[ -n "$ENDPOINT" ] && [ -n "$WAN_GW" ] && ip route del "$ENDPOINT/32" via "$WAN_GW" 2>/dev/null

# 注意: ip rule del 需要完整规则或 priority，按 priority 删最稳
ip rule del priority 32765 2>/dev/null
ip rule del priority 32764 2>/dev/null

logger -t wg-down "清理完成，默认路由恢复 eth0 直连"
exit 0
