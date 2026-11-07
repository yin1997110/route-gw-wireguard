#!/bin/bash
# dnsmasq-healthcheck.sh — DNS 存活自检 + 自愈（由 dnsmasq-healthcheck.timer 每 5 分钟触发）
#
# 背景（2026-11-05 事故）:
#   本机装 docker.io 时 apt 顺带装了 ubuntu-fan，它投放的 /etc/dnsmasq.d/ubuntu-fan
#   含 `bind-interfaces`，与本项目 /etc/dnsmasq.conf 里的 `bind-dynamic` 互斥。
#   dnsmasq 当时仍在运行（读的是旧配置），直到每日 04:30 的 update-lists.sh 重启
#   dnsmasq 才暴露：`cannot set --bind-interfaces and --bind-dynamic` → 启动失败，
#   全内网 DNS 静默中断 4.5 小时。dnsmasq --test 只做语法检查，查不出这个冲突。
#
# 判定: 进程 active 且 127.0.0.1:53 在监听。任一不满足即重启并记录到 journal(tag=dns-health)。
# 重启仍失败时以非 0 退出，systemd 会把单元标成 failed（systemctl --failed 可见）。
set -u

TAG="dns-health"
log() { logger -t "$TAG" -- "$*"; }
alive() { systemctl is-active --quiet dnsmasq && ss -lntu 2>/dev/null | grep -qE '127\.0\.0\.1:53\b'; }

alive && exit 0

log "异常: active=$(systemctl is-active dnsmasq 2>&1), 53端口监听=$(ss -lntu 2>/dev/null | grep -cE '127\.0\.0\.1:53\b') -> 尝试重启"
if systemctl restart dnsmasq; then
    sleep 1
    if alive; then
        log "重启成功, DNS 已自愈"
        exit 0
    fi
fi

log "重启失败, 需人工介入. 最近 10 行日志:"
journalctl -u dnsmasq -n 10 --no-pager 2>&1 | while read -r L; do log "    $L"; done
exit 1
