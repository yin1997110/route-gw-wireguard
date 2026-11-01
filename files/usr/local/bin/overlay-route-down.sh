#!/bin/bash
# overlay-route-down.sh — 清理 overlay-route-up.sh 建的两条独立链。
set -u

log() { logger -t overlay-down -- "$*"; echo "[overlay-down] $*"; }

for hook in POSTROUTING; do
    while iptables -t nat -D "$hook" -j OVERLAY_NAT 2>/dev/null; do :; done
done
while iptables -D FORWARD -j OVERLAY_FWD 2>/dev/null; do :; done

iptables -t nat -F OVERLAY_NAT 2>/dev/null || true
iptables -t nat -X OVERLAY_NAT 2>/dev/null || true
iptables -F OVERLAY_FWD 2>/dev/null || true
iptables -X OVERLAY_FWD 2>/dev/null || true

log "overlay 规则已清理"
exit 0
