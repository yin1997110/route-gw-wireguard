#!/bin/bash
# wg-route-up.sh — WireGuard PostUp 钩子：部署分流策略路由 (LXC 201)
#
# 相比旧版 (CT107) 的修复:
#   1. ENDPOINT 改为从 /etc/wireguard/wg0.conf 静态解析，不再依赖
#      `wg show endpoints`（PostUp 时通常还没握手，旧版会静默漏加 anti-loop 路由）
#   2. WAN_GW/WAN_IF 自动探测主表默认路由，不再硬编码
set -u

WG_CONF="/etc/wireguard/wg0.conf"
CHINA_LIST="/etc/china_ip_list.txt"
TEST_NET="192.168.99.0/24"

# 1. 探测 WAN 出口（主表默认路由）
WAN_GW=$(ip route show default | awk '/^default/{print $3; exit}')
WAN_IF=$(ip route show default | awk '/^default/{print $5; exit}')
[ -z "$WAN_GW" ] && { logger -t wg-up "找不到默认路由，跳过部署"; exit 0; }

# 2. 从配置文件解析 WG 对端 IP（anti-loop 用，与握手状态无关）
ENDPOINT=$(awk -F'[ =:]' '/^Endpoint/{print $4; exit}' "$WG_CONF")

logger -t wg-up "开始部署分流路由 (wan=$WAN_IF via $WAN_GW, endpoint=$ENDPOINT)"

# 3. 策略路由
ip rule add from all lookup main suppress_prefixlength 0 priority 32764 2>/dev/null
ip rule add not from all fwmark 0xca6c lookup 51820 priority 32765 2>/dev/null

# 4. anti-loop: WG 对端 IP 必须走 WAN 直连，否则隧道流量套隧道死循环
[ -n "$ENDPOINT" ] && ip route replace "$ENDPOINT/32" via "$WAN_GW" dev "$WAN_IF" 2>/dev/null

# 5. 国内 IP 直连路由（灌入主表，靠最长前缀匹配压过 default）
if [ -f "$CHINA_LIST" ]; then
    COUNT=0
    while IFS= read -r cidr; do
        [ -z "$cidr" ] && continue
        ip route replace "$cidr" via "$WAN_GW" dev "$WAN_IF" 2>/dev/null && COUNT=$((COUNT+1))
    done < "$CHINA_LIST"
    logger -t wg-up "国内直连路由: $COUNT 条"
else
    logger -t wg-up "警告: $CHINA_LIST 不存在，国内流量将全部走隧道"
fi

# 6. NAT: 测试内网 192.168.99.0/24 经 201 出网
iptables -t nat -C POSTROUTING -s "$TEST_NET" -o "$WAN_IF" -j MASQUERADE 2>/dev/null || \
    iptables -t nat -A POSTROUTING -s "$TEST_NET" -o "$WAN_IF" -j MASQUERADE
iptables -t nat -C POSTROUTING -s "$TEST_NET" -o wg0 -j MASQUERADE 2>/dev/null || \
    iptables -t nat -A POSTROUTING -s "$TEST_NET" -o wg0 -j MASQUERADE

# 7. FORWARD: 放行测试网段（含 DNS 查询转发）
iptables -C FORWARD -s "$TEST_NET" -j ACCEPT 2>/dev/null || iptables -I FORWARD -s "$TEST_NET" -j ACCEPT
iptables -C FORWARD -d "$TEST_NET" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || \
    iptables -I FORWARD -d "$TEST_NET" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT

# 7b. TCP MSS 钳制: 对端发来的 1460 分段在转发进 wg0(1420) 时因 DF 位无法分片，
#     会造成"握手成功但大数据黑洞"，必须按出接口 PMTU 钳制 SYN 中的 MSS
iptables -t mangle -C FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || \
    iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu

# 8. 开启转发
sysctl -w net.ipv4.ip_forward=1 >/dev/null

logger -t wg-up "分流路由部署完成"
exit 0
