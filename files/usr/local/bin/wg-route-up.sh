#!/bin/bash
# wg-route-up.sh — WireGuard PostUp 钩子：同网段单臂旁路由分流 (单机旁路由)
#
# 形态: 只有一块 LAN 网卡。LAN 与 WAN 是同一个接口（默认路由所在网卡），
#       同网段主机把「默认网关 + DNS」都指向本机即可分流：
#         国内目标  -> 主表里的国内明细路由 -> 上游网关直连
#         其余目标  -> 表 51820 -> wg0
#       客户端流量从 eth0 进来，转发后从同一个 eth0（直连）或 wg0（隧道）出去，
#       因此必须在 POSTROUTING 按 LAN 网段做 MASQUERADE，否则隧道对端不知道
#       怎么把 192.168.x.x 的回包送回来。
#
# 本脚本不写死任何 IP / 网段：WAN/LAN 接口、LAN 地址、LAN 网段全部在运行时
# 从默认路由和网卡地址现算。换网络（改 IP、换网段、甚至换默认路由网卡）后
# 只要重新拉起 wg-quick@wg0 就会自动跟随。
#
# 可选覆盖（一般不需要）：/etc/default/route-gw
#   ROUTE_GW_LAN_IF=eth1      # LAN 与 WAN 不是同一块网卡时才需要
#   ROUTE_GW_WG_IF=wg0
set -u

WG_CONF="${WG_CONF:-/etc/wireguard/wg0.conf}"
WG_IF="${WG_IF:-wg0}"
CHINA_LIST="${CHINA_LIST:-/etc/china_ip_list.txt}"
DNS_LISTEN_CONF="${DNS_LISTEN_CONF:-/etc/dnsmasq.d/00-listen.conf}"

# 可选的本机覆盖文件（不写进仓库）
[ -r /etc/default/route-gw ] && . /etc/default/route-gw

NAT_CHAIN="ROUTE_GW_NAT"
FWD_CHAIN="ROUTE_GW_FWD"
MSS_CHAIN="ROUTE_GW_MSS"

log() { logger -t wg-up -- "$*"; echo "[wg-up] $*"; }

# ---------------------------------------------------------------- 0. 依赖检查
command -v ip >/dev/null 2>&1 || { log "缺少 iproute2，退出"; exit 0; }
command -v iptables >/dev/null 2>&1 || { log "缺少 iptables，退出"; exit 0; }

# ---------------------------------------------------------------- 1. 现算 WAN / LAN
WAN_IF=$(ip route show default | awk '/^default/{for(i=1;i<=NF;i++) if($i=="dev"){print $(i+1); exit}}')
WAN_GW=$(ip route show default | awk '/^default/{for(i=1;i<=NF;i++) if($i=="via"){print $(i+1); exit}}')
if [ -z "${WAN_GW:-}" ] || [ -z "${WAN_IF:-}" ]; then
    log "找不到默认路由，跳过部署"
    exit 0
fi

LAN_IF="${ROUTE_GW_LAN_IF:-$WAN_IF}"
WG_IF="${ROUTE_GW_WG_IF:-$WG_IF}"

# 默认路由的源地址就是本机在 LAN 上的地址（多地址时也能选对）
LAN_IP=$(ip route get "$WAN_GW" 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')
if [ -z "${LAN_IP:-}" ]; then
    LAN_IP=$(ip -4 -o addr show dev "$LAN_IF" scope global 2>/dev/null | awk 'NR==1{split($4,a,"/"); print a[1]}')
fi
if [ -z "${LAN_IP:-}" ]; then
    log "接口 $LAN_IF 上没有 IPv4 地址，跳过部署"
    exit 0
fi

# 从 "IP/前缀" 现算网络地址，不依赖 ipcalc
LAN_ADDR=$(ip -4 -o addr show dev "$LAN_IF" scope global 2>/dev/null | \
    awk -v ip="$LAN_IP" '{split($4,a,"/"); if(a[1]==ip){print $4; exit}}')
[ -z "${LAN_ADDR:-}" ] && LAN_ADDR=$(ip -4 -o addr show dev "$LAN_IF" scope global 2>/dev/null | awk 'NR==1{print $4}')
[ -z "${LAN_ADDR:-}" ] && { log "拿不到 $LAN_IF 的地址/前缀，跳过部署"; exit 0; }
LAN_PREFIX="${LAN_ADDR#*/}"
LAN_IP="${LAN_ADDR%/*}"

ip_to_int() { local IFS=.; read -r a b c d <<< "$1"; echo $(( (a << 24) + (b << 16) + (c << 8) + d )); }
int_to_ip() { echo "$(( ($1 >> 24) & 255 )).$(( ($1 >> 16) & 255 )).$(( ($1 >> 8) & 255 )).$(( $1 & 255 ))"; }
LAN_MASK=$(( (0xFFFFFFFF << (32 - LAN_PREFIX)) & 0xFFFFFFFF ))
LAN_NET="$(int_to_ip $(( $(ip_to_int "$LAN_IP") & LAN_MASK )))/$LAN_PREFIX"

# 从配置文件静态解析 WG 对端（PostUp 阶段通常还没握手，不能依赖 wg show）
ENDPOINT=$(sed -n 's/^[[:space:]]*Endpoint[[:space:]]*=[[:space:]]*//p' "$WG_CONF" 2>/dev/null | head -n1 | tr -d '[:space:]')
case "$ENDPOINT" in
    \[*\]:*) ENDPOINT="${ENDPOINT#\[}"; ENDPOINT="${ENDPOINT%%]*}" ;;   # [IPv6]:port
    *:*)     ENDPOINT="${ENDPOINT%:*}" ;;                               # IPv4:port
esac

log "旁路由模式: LAN=$LAN_IF $LAN_IP/$LAN_PREFIX net=$LAN_NET, 上游=$WAN_IF via $WAN_GW, 隧道=$WG_IF, endpoint=${ENDPOINT:-?}"

# ---------------------------------------------------------------- 2. 策略路由
# 32764: 主表里"有明细路由"的目标先按主表走（国内直连、endpoint 例外），
#        但 suppress_prefixlength 0 让主表默认路由不生效。
# 32765: 其余未打 fwmark 的流量查 51820（wg0 的 0/1 + 128/1）。
# 先删同优先级旧规则，保证重复执行后规则唯一。
# 注意：这两条规则是分流的总开关，删除后如果 add 失败，全网会悄悄回到 .1 直连。
# 所以这里带重试，并在最后显式校验；面板 health_loop 也会每 3 秒兜底补一次。
ip rule del priority 32764 2>/dev/null || true
ip rule del priority 32765 2>/dev/null || true

add_rule() {
    local prio="$1"; shift
    local i
    for i in 1 2 3 4 5; do
        ip rule add "$@" priority "$prio" 2>/dev/null && return 0
        ip rule del priority "$prio" 2>/dev/null || true
        sleep 0.2
    done
    return 1
}

add_rule 32764 from all lookup main suppress_prefixlength 0 || log "严重: 32764 策略规则补加失败"
add_rule 32765 not from all fwmark 0xca6c lookup 51820 || log "严重: 32765 策略规则补加失败"
if ! ip rule show | grep -q '^32764:'; then
    log "严重: 32764 策略规则不存在，分流会失效（面板 health_loop 会兜底重试）"
fi
if ! ip rule show | grep -q '^32765:'; then
    log "严重: 32765 策略规则不存在，分流会失效（面板 health_loop 会兜底重试）"
fi

# anti-loop: 隧道对端必须走 WAN 直连，否则 WG 自己的包会被 0/1 路由再灌回隧道
if [ -n "${ENDPOINT:-}" ] && [ "${ENDPOINT#*:}" = "$ENDPOINT" ]; then
    ip route replace "$ENDPOINT/32" via "$WAN_GW" dev "$WAN_IF" 2>/dev/null || true
fi

# ---------------------------------------------------------------- 3. 国内 IP 直连
if [ -f "$CHINA_LIST" ]; then
    # 7400+ 条路由逐条 fork `ip` 在 J1900 这类低功耗机器上要 40~50 秒，
    # 改成 ip -batch 单进程灌入，开机/重载从几十秒降到 1~2 秒。
    BATCH=$(mktemp /tmp/route-gw-batch.XXXXXX) || BATCH=""
    COUNT=0
    if [ -n "$BATCH" ]; then
        while IFS= read -r cidr; do
            [ -z "$cidr" ] && continue
            printf 'route replace %s via %s dev %s\n' "$cidr" "$WAN_GW" "$WAN_IF" >> "$BATCH"
            COUNT=$((COUNT + 1))
        done < "$CHINA_LIST"
        if [ "$COUNT" -gt 0 ]; then
            ip -force -batch "$BATCH" >/dev/null 2>&1 || \
                log "警告: ip -batch 有失败项，已尽量灌入"
        fi
        rm -f "$BATCH"
    else
        # mktemp 失败时退回逐条模式
        while IFS= read -r cidr; do
            [ -z "$cidr" ] && continue
            ip route replace "$cidr" via "$WAN_GW" dev "$WAN_IF" 2>/dev/null && COUNT=$((COUNT + 1))
        done < "$CHINA_LIST"
    fi
    log "国内直连路由: $COUNT 条"
else
    log "警告: $CHINA_LIST 不存在，国内流量将全部走隧道"
fi

# ---------------------------------------------------------------- 4. NAT（按 LAN 网段，动态）
# 清理旧版/手工遗留的 MASQUERADE：只删"出口是本机 WAN/WG"或"源是本 LAN 网段"的规则，
# 保留端口转发等带 -d 指定目标的 NAT 规则，避免误删同机其它服务。
while IFS= read -r rule; do
    case "$rule" in
        *"$NAT_CHAIN"*) continue ;;
        *"-j MASQUERADE"*)
            case "$rule" in
                *"-o $WAN_IF"*|*"-o $WG_IF"*|*"-s $LAN_NET"*)
                    iptables -t nat -D POSTROUTING ${rule#-A POSTROUTING } 2>/dev/null || true
                    ;;
            esac
            ;;
    esac
done < <(iptables -t nat -S POSTROUTING 2>/dev/null)

iptables -t nat -n -L "$NAT_CHAIN" >/dev/null 2>&1 || iptables -t nat -N "$NAT_CHAIN"
iptables -t nat -F "$NAT_CHAIN"
iptables -t nat -C POSTROUTING -j "$NAT_CHAIN" 2>/dev/null || \
    iptables -t nat -I POSTROUTING 1 -j "$NAT_CHAIN"

# 注意: nft 后端的 iptables 不允许同时出现两个 -s（即使一个取反），
# 所以这里只按 LAN 网段匹配；本机自己发出的流量 SNAT 成本机地址是幂等的，无害。
# 客户端 -> 上游直连：SNAT 成本机 LAN 地址，回包才会经过本机
iptables -t nat -A "$NAT_CHAIN" -s "$LAN_NET" ! -d "$LAN_NET" -o "$WAN_IF" -j MASQUERADE
# 客户端 -> 隧道：SNAT 成 wg0 地址，对端只认识 10.x 的隧道源
iptables -t nat -A "$NAT_CHAIN" -s "$LAN_NET" ! -d "$LAN_NET" -o "$WG_IF" -j MASQUERADE

# ---------------------------------------------------------------- 5. FORWARD
iptables -n -L "$FWD_CHAIN" >/dev/null 2>&1 || iptables -N "$FWD_CHAIN"
iptables -F "$FWD_CHAIN"
iptables -C FORWARD -j "$FWD_CHAIN" 2>/dev/null || iptables -I FORWARD 1 -j "$FWD_CHAIN"
iptables -A "$FWD_CHAIN" -i "$LAN_IF" -s "$LAN_NET" -j ACCEPT
iptables -A "$FWD_CHAIN" -o "$LAN_IF" -d "$LAN_NET" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
iptables -A "$FWD_CHAIN" -i "$WG_IF" -j ACCEPT
iptables -A "$FWD_CHAIN" -o "$WG_IF" -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT

# ---------------------------------------------------------------- 6. TCP MSS 钳制
# wg0 MTU 1420，转发大包时按出接口 PMTU 压 SYN 的 MSS，避免"能握手但大流量黑洞"
iptables -t mangle -n -L "$MSS_CHAIN" >/dev/null 2>&1 || iptables -t mangle -N "$MSS_CHAIN"
iptables -t mangle -F "$MSS_CHAIN"
iptables -t mangle -C FORWARD -j "$MSS_CHAIN" 2>/dev/null || iptables -t mangle -I FORWARD 1 -j "$MSS_CHAIN"
iptables -t mangle -A "$MSS_CHAIN" -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu

# ---------------------------------------------------------------- 7. 内核参数
sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true
# 同一块网卡进出时必须关 ICMP redirect，否则手机会被"重定向"到上游网关，绕过本机
sysctl -w net.ipv4.conf.all.send_redirects=0 >/dev/null 2>&1 || true
sysctl -w "net.ipv4.conf.$LAN_IF.send_redirects=0" >/dev/null 2>&1 || true
sysctl -w net.ipv4.conf.all.accept_redirects=0 >/dev/null 2>&1 || true
sysctl -w "net.ipv4.conf.$LAN_IF.accept_redirects=0" >/dev/null 2>&1 || true
# 松散 rp_filter：单臂旁路由的回程可能从 wg0/eth0 不同路径回来
sysctl -w net.ipv4.conf.all.rp_filter=2 >/dev/null 2>&1 || true
sysctl -w "net.ipv4.conf.$LAN_IF.rp_filter=2" >/dev/null 2>&1 || true
sysctl -w "net.ipv4.conf.$WG_IF.rp_filter=0" >/dev/null 2>&1 || true

# ---------------------------------------------------------------- 8. DNS 监听接口跟随 LAN
# dnsmasq 用 bind-dynamic + interface=<LAN_IF>，换 IP 不用改配置；接口名变了才重写。
if [ -d "$(dirname "$DNS_LISTEN_CONF")" ]; then
    DESIRED="# generated by wg-route-up.sh — 跟随默认路由网卡，勿手改
interface=lo
interface=$LAN_IF"
    CURRENT=$(cat "$DNS_LISTEN_CONF" 2>/dev/null || true)
    if [ "$CURRENT" != "$DESIRED" ]; then
        printf '%s\n' "$DESIRED" > "$DNS_LISTEN_CONF"
        log "DNS 监听接口已更新为 lo + $LAN_IF"
        if systemctl is-active --quiet dnsmasq 2>/dev/null; then
            systemctl restart dnsmasq 2>/dev/null || log "dnsmasq 重启失败，请手工 systemctl restart dnsmasq"
        fi
    fi
fi

log "旁路由分流部署完成 (LAN $LAN_NET, 网关 $LAN_IP)"
exit 0
