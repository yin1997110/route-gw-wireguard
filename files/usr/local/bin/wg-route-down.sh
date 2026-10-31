#!/bin/bash
# wg-route-down.sh — WireGuard PostDown 钩子：清理同网段旁路由的分流规则 (LXC 201)
#
# 只清理本方案自己加的东西：策略路由、国内明细路由、endpoint 例外、NAT/FORWARD/MSS
# 三条自定义链。不碰主表默认路由，也不停 dnsmasq。
set -u

WG_CONF="${WG_CONF:-/etc/wireguard/wg0.conf}"
WG_IF="${WG_IF:-wg0}"
CHINA_LIST="${CHINA_LIST:-/etc/china_ip_list.txt}"
NAT_CHAIN="ROUTE_GW_NAT"
FWD_CHAIN="ROUTE_GW_FWD"
MSS_CHAIN="ROUTE_GW_MSS"

[ -r /etc/default/route-gw ] && . /etc/default/route-gw
WG_IF="${ROUTE_GW_WG_IF:-$WG_IF}"

log() { logger -t wg-down -- "$*"; echo "[wg-down] $*"; }

WAN_IF=$(ip route show default | awk '/^default/{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')
WAN_GW=$(ip route show default | awk '/^default/{for(i=1;i<=NF;i++) if($i=="via"){print $(i+1); exit}}')

ENDPOINT=$(sed -n 's/^[[:space:]]*Endpoint[[:space:]]*=[[:space:]]*//p' "$WG_CONF" 2>/dev/null | head -n1 | tr -d '[:space:]')
case "$ENDPOINT" in
    \[*\]:*) ENDPOINT="${ENDPOINT#\[}"; ENDPOINT="${ENDPOINT%%]*}" ;;
    *:*)     ENDPOINT="${ENDPOINT%:*}" ;;
esac

log "清理旁路由分流 (endpoint=${ENDPOINT:-?} gw=${WAN_GW:-?})"

# 国内明细路由：按列表批量删（主表里可能还有其它路由，不能 flush）。
# 逐条 fork `ip` 要 40 秒，ip -batch 后 1 秒级。
if [ -f "$CHINA_LIST" ] && [ -n "${WAN_GW:-}" ]; then
    BATCH=$(mktemp /tmp/route-gw-down.XXXXXX) || BATCH=""
    if [ -n "$BATCH" ]; then
        while IFS= read -r cidr; do
            [ -z "$cidr" ] && continue
            printf 'route del %s via %s dev %s\n' "$cidr" "$WAN_GW" "$WAN_IF" >> "$BATCH"
        done < "$CHINA_LIST"
        ip -force -batch "$BATCH" >/dev/null 2>&1 || true
        rm -f "$BATCH"
    else
        while IFS= read -r cidr; do
            [ -z "$cidr" ] && continue
            ip route del "$cidr" via "$WAN_GW" 2>/dev/null || true
        done < "$CHINA_LIST"
    fi
fi

if [ -n "${ENDPOINT:-}" ] && [ -n "${WAN_GW:-}" ] && [ "${ENDPOINT#*:}" = "$ENDPOINT" ]; then
    ip route del "$ENDPOINT/32" via "$WAN_GW" 2>/dev/null || true
fi

# 策略路由按优先级删（比按内容匹配稳）
ip rule del priority 32765 2>/dev/null || true
ip rule del priority 32764 2>/dev/null || true

# 自定义链：先摘跳转，再清空，最后删链。重复执行无副作用。
for spec in "nat POSTROUTING $NAT_CHAIN" "filter FORWARD $FWD_CHAIN" "mangle FORWARD $MSS_CHAIN"; do
    set -- $spec
    table=$1; hook=$2; chain=$3
    if iptables -t "$table" -n -L "$chain" >/dev/null 2>&1; then
        while iptables -t "$table" -D "$hook" -j "$chain" 2>/dev/null; do :; done
        iptables -t "$table" -F "$chain" 2>/dev/null || true
        iptables -t "$table" -X "$chain" 2>/dev/null || true
    fi
done

# NAT 清理后主表默认路由仍在（wg-quick 只删 51820 表），无需恢复
log "清理完成：策略路由/NAT/FORWARD/MSS 已撤销，主表默认路由未动"
exit 0
