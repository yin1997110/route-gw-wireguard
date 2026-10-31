#!/bin/bash
# update-lists.sh — 每日更新国内 IP 列表与 GFW 域名列表，并重新灌入分流路由
#
# 数据源:
#   china_ip_list  -> /etc/china_ip_list.txt   (ip route 国内直连)
#   gfwlist        -> /etc/dnsmasq.d/99-gfw.conf (DNS 按域名走隧道)
# 安全机制: 临时目录 + 下载/行数校验 + 原子替换，失败保留旧文件。
# 注意: gfwlist 的 @@ 例外规则被跳过（保持 dnsmasq 默认上游），如需例外直连需另行处理。
set -u

CHINA_URL="https://raw.githubusercontent.com/17mon/china_ip_list/master/china_ip_list.txt"
GFW_URL="https://raw.githubusercontent.com/gfwlist/gfwlist/master/gfwlist.txt"

# 隧道内 DNS 上游不写死在仓库里：优先取本机覆盖文件/环境变量，
# 未配置时才落到文档占位值（198.51.100.53 不可用，仅用于自包含演示）。
[ -r /etc/default/route-gw ] && . /etc/default/route-gw
GFW_DNS="${GW_GFW_DNS:-198.51.100.53}"

CHINA_LIST="/etc/china_ip_list.txt"
GFW_CONF="/etc/dnsmasq.d/99-gfw.conf"
MIN_IPS=5000
MIN_DOMAINS=1000

TMP=$(mktemp -d /tmp/update-lists.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

log() { logger -t route-update -- "$*"; echo "[route-update] $*"; }

fetch() { curl -fsSL --connect-timeout 15 --retry 3 --retry-delay 5 -m 180 -o "$2" "$1"; }

# ---------- 1. 国内 IP 列表 ----------
OK_IP=0
if fetch "$CHINA_URL" "$TMP/china.txt"; then
    N=$(awk 'END{print NR}' "$TMP/china.txt")
    if [ "$N" -ge "$MIN_IPS" ] && grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$' "$TMP/china.txt"; then
        mv -f "$TMP/china.txt" "$CHINA_LIST"
        OK_IP=1
        log "china_ip_list 已更新: $N 条"
    else
        log "错误: china_ip_list 校验不通过 ($N 条)，保留旧列表"
    fi
else
    log "错误: china_ip_list 下载失败，保留旧列表"
fi

# ---------- 2. gfwlist -> dnsmasq 域名规则 ----------
OK_DNS=0
if fetch "$GFW_URL" "$TMP/gfw.b64"; then
    # gfwlist.txt 头部有 [AutoProxy]/!/----- 标记行，剥掉后整体是 base64
    grep -vE '^(\[|!|-----)' "$TMP/gfw.b64" | tr -d '\r\n' | base64 -d 2>/dev/null > "$TMP/gfw.abp" || true
    awk -v dns="$GFW_DNS" '
        /^\[/{next}
        /^@@/{next}                       # 例外规则: 跳过，不强行走直连
        {
            gsub(/\r/,""); gsub(/^[ \t]+|[ \t]+$/,"")
            sub(/^\|\|?/,""); sub(/^https?:\/\//,""); sub(/^\/\./,"")
            sub(/[\/^#$].*$/,"")
            if ($0 ~ /^[A-Za-z0-9._-]+\.[A-Za-z][A-Za-z]+$/) {
                d = tolower($0); gsub(/^-+|-+$/,"",d)
                if (d != "" ) seen[d]=1
            }
        }
        END{ for (d in seen) print "server=/" d "/" dns }
    ' "$TMP/gfw.abp" | sort -o "$TMP/99-gfw.conf"
    N=$(grep -c '^server=' "$TMP/99-gfw.conf" || true)
    if [ "${N:-0}" -ge "$MIN_DOMAINS" ]; then
        mv -f "$TMP/99-gfw.conf" "$GFW_CONF"
        OK_DNS=1
        log "gfwlist 已更新: $N 条域名规则"
    else
        log "错误: gfwlist 校验不通过 ($N 条)，保留旧配置"
    fi
else
    log "错误: gfwlist 下载失败，保留旧配置"
fi

if [ "$OK_DNS" = "1" ] && command -v systemctl >/dev/null && systemctl is-active dnsmasq >/dev/null 2>&1; then
    systemctl restart dnsmasq && log "dnsmasq 已重启"
fi

# ---------- 3. 隧道在跑就立即重新灌入国内直连路由（同时校准 LAN 网段/NAT） ----------
if ip link show wg0 >/dev/null 2>&1 && [ -f "$CHINA_LIST" ]; then
    /usr/local/bin/wg-route-up.sh >/dev/null 2>&1 && log "国内直连路由与旁路由 NAT 已刷新"
fi

exit 0
