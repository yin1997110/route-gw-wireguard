#!/bin/bash
# install-zerotier.sh — 安装 ZeroTier、加入指定网络，并启用 LAN -> overlay 的 NAT。
#
# 用法:
#   bash install-zerotier.sh <16位网络ID>
#   ZT_NETWORK_ID=<16位网络ID> bash install-zerotier.sh
#
# 网络 ID 不写进仓库；脚本只把它作为参数传给 zerotier-cli。
set -euo pipefail

NET="${1:-${ZT_NETWORK_ID:-}}"
if ! printf '%s' "$NET" | grep -qE '^[0-9a-fA-F]{16}$'; then
    echo "用法: bash $0 <16位ZeroTier网络ID>" >&2
    exit 1
fi

echo "[1/3] 安装 ZeroTier"
if ! command -v zerotier-cli >/dev/null 2>&1; then
    curl -fsSL https://install.zerotier.com | bash
fi
systemctl enable --now zerotier-one

echo "[2/3] 加入网络 $NET"
zerotier-cli join "$NET" || true
for _ in $(seq 1 30); do
    line=$(zerotier-cli listnetworks 2>/dev/null | grep -i "$NET" || true)
    case "$line" in
        *" OK "*) break ;;
    esac
    sleep 2
done
zerotier-cli listnetworks || true

echo "[3/3] 启用 overlay NAT"
if [ -x /usr/local/bin/overlay-route-up.sh ] && [ -f /etc/systemd/system/route-gw-overlay.service ]; then
    systemctl enable --now route-gw-overlay.service
    systemctl --no-pager status route-gw-overlay.service | head -8 || true
else
    echo "未找到 overlay-route-up.sh / route-gw-overlay.service；请先运行 install.sh" >&2
    exit 0
fi

echo "完成。若网络是私有的，还需要在 ZeroTier Central 授权这台成员。"
