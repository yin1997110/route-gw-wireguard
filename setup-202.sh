#!/bin/bash
# setup-202.sh — 在 LXC 202 (client) 内以 root 执行
# 让 202 跟随 201 分流: 网关已在 PVE 侧指向 192.168.99.1，这里只管 DNS
set -euo pipefail

echo "[1/2] 停用 systemd-resolved（resolv.conf 直连 201 的 dnsmasq）"
systemctl disable --now systemd-resolved 2>/dev/null || true
rm -f /etc/resolv.conf
printf 'nameserver 192.168.99.1\n' > /etc/resolv.conf

echo "[2/2] 自检"
ping -c1 -W2 192.168.99.1 >/dev/null && echo "网关 201 可达"
getent hosts github.com >/dev/null && echo "DNS 可用"
echo "DONE"
