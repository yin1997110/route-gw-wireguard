#!/bin/bash
# setup-202.sh — 同网段客户端接入（LXC 202 / 任意同网段主机）
#
# 用法（在客户端内以 root 执行）:
#   bash setup-202.sh                 # 旁路由 IP 取当前默认网关
#   bash setup-202.sh 192.168.1.212   # 显式指定旁路由 IP
#
# 前提: 客户端的「默认网关」已经指向旁路由。LXC 的网关由 PVE 管理，需在宿主机:
#   pct set 202 --net0 name=eth0,bridge=vmbr0,gw=<旁路由IP>,ip=<客户端IP>/24
#   pct set 202 --nameserver <旁路由IP>
# 本脚本只负责容器内的 resolv.conf 与连通性自检，不改路由表。
set -euo pipefail

GW_IP="${1:-$(ip route show default | awk '/^default/{print $3; exit}')}"
if [ -z "${GW_IP:-}" ]; then
    echo "找不到默认网关，请显式传入旁路由 IP: bash $0 <旁路由IP>" >&2
    exit 1
fi
if ! printf '%s' "$GW_IP" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "IP 格式不正确: $GW_IP" >&2
    exit 1
fi

echo "[1/3] 校验默认网关"
CUR_GW=$(ip route show default | awk '/^default/{print $3; exit}')
if [ "${CUR_GW:-}" != "$GW_IP" ]; then
    echo "  当前默认网关是 ${CUR_GW:-无}，不是 $GW_IP"
    echo "  LXC 请先在 PVE 执行: pct set 202 --net0 name=eth0,bridge=vmbr0,gw=$GW_IP,ip=<本机IP>/24"
    echo "  物理机/虚拟机请把默认网关改为 $GW_IP 后重跑本脚本"
    exit 1
fi
echo "  默认网关 = $GW_IP"

echo "[2/3] 停用 systemd-resolved，resolv.conf 指向旁路由 DNS"
systemctl disable --now systemd-resolved 2>/dev/null || true
rm -f /etc/resolv.conf
printf 'nameserver %s\n' "$GW_IP" > /etc/resolv.conf
echo "  已写入 nameserver $GW_IP（LXC 重启会被 PVE 覆写，务必同时 pct set --nameserver）"

echo "[3/3] 自检"
ping -c1 -W2 "$GW_IP" >/dev/null && echo "  ✓ 旁路由 $GW_IP 可达"
getent hosts baidu.com >/dev/null && echo "  ✓ DNS 解析可用"
echo "DONE: 同网段客户端已指向 $GW_IP（网关 + DNS 同一个地址）"
