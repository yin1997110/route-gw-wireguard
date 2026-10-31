#!/bin/bash
# install.sh — 在 LXC 201 (router) 内以 root 执行的一键安装
# 用法: 把 route-gw-deploy 整个目录放到 /opt/ 下，然后 bash /opt/route-gw-deploy/install.sh
set -euo pipefail

BASE="$(cd "$(dirname "$0")" && pwd)"
FILES="$BASE/files"
export DEBIAN_FRONTEND=noninteractive

echo "[1/8] 安装软件包"
# 等待可能残留的 apt/dpkg 锁（首次开机模板初始化常见），最多 5 分钟
for i in $(seq 1 60); do
    fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || break
    echo "  dpkg 锁被占用，等待... ($i/60)"; sleep 5
done
DEBIAN_FRONTEND=noninteractive dpkg --configure -a || true
apt-get update -qq
apt-get install -y -qq wireguard-tools dnsmasq curl ca-certificates cron iptables iproute2

echo "[2/8] 投放配置文件"
install -d -m 700 /etc/wireguard
install -d /usr/local/bin /etc/dnsmasq.d /etc/cron.d /etc/sysctl.d
# 防 CRLF 残留（从 Windows 侧打包时可能出现）
for f in "$FILES"/usr/local/bin/*.sh "$FILES"/etc/wireguard/wg0.conf; do sed -i 's/\r$//' "$f"; done
install -m 600 "$FILES/etc/wireguard/wg0.conf" /etc/wireguard/wg0.conf
install -m 755 "$FILES"/usr/local/bin/*.sh /usr/local/bin/
install -m 644 "$FILES/etc/dnsmasq.conf" /etc/dnsmasq.conf
install -m 644 "$FILES/etc/dnsmasq.d/98-custom-domain.conf" /etc/dnsmasq.d/
install -m 644 "$FILES/etc/cron.d/route-lists" /etc/cron.d/
install -m 644 "$FILES/etc/sysctl.d/99-route-gw.conf" /etc/sysctl.d/

echo "[3/8] systemd 依赖顺序"
install -d /etc/systemd/system/dnsmasq.service.d
install -m 644 "$FILES/etc/systemd/system/dnsmasq.service.d/override.conf" /etc/systemd/system/dnsmasq.service.d/
systemctl daemon-reload
sysctl --system >/dev/null 2>&1 || true

echo "[4/8] 接管 DNS: 停用 systemd-resolved，resolv.conf 指向本机 dnsmasq"
systemctl disable --now systemd-resolved 2>/dev/null || true
rm -f /etc/resolv.conf
printf 'nameserver 127.0.0.1\n' > /etc/resolv.conf
# PVE 会在容器重启时按 pct --nameserver 重写 resolv.conf（安装文档里有对应命令）

echo "[5/8] 拉起 WireGuard 隧道"
systemctl enable --now wg-quick@wg0

echo "[6/8] 首次拉取数据源（github 走隧道下载）"
/usr/local/bin/update-lists.sh || echo "WARN: 首次更新失败，隧道恢复后手动执行 /usr/local/bin/update-lists.sh"

echo "[7/8] 启动 dnsmasq 与 cron"
systemctl enable --now dnsmasq cron
systemctl restart dnsmasq

echo "[8/8] 状态快照"
sleep 2
echo "--- wg ---";      wg show wg0 | head -4 || true
echo "--- rule ---";    ip rule show | grep -E '32764|32765' || echo "MISSING RULES"
echo "--- table ---";   ip route show table 51820 || true
echo "--- china ---";   wc -l /etc/china_ip_list.txt 2>/dev/null || echo "MISSING LIST"
echo "--- gfw ---";     grep -c '^server=' /etc/dnsmasq.d/99-gfw.conf 2>/dev/null || echo "MISSING GFW"
echo "--- svc ---";     systemctl is-active wg-quick@wg0 dnsmasq cron
echo "DONE"
