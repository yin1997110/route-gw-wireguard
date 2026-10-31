#!/bin/bash
# 职责: 核对 wg0.conf 里写的对端 与 隧道里真实生效的对端 是否一致。
#       面板换节点分叉(改文件成功、syncconf 失败)时用它一眼看出来。
# 用法: 在 CT201 上 bash peer-check.sh；或 PVE 侧 pct exec 201 -- bash /opt/route-gw-deploy/tools/peer-check.sh
E=$(grep -oE 'Endpoint = [0-9.:]+' /etc/wireguard/wg0.conf | awk '{print $3}')
L=$(wg show wg0 dump | awk 'NR==2{print $3}')
T=$(wg show wg0 dump | awk 'NR==2{print $5}')
if [ -z "$L" ]; then echo "隧道无对端(wg0 未拉起)"; exit 1; fi
if [ "$E" = "$L" ]; then S=一致; else S=分叉; fi
echo "conf=$E live=$L 文件/隧道=$S 握手距今=$(( $(date +%s) - T ))s"
[ "$S" = 一致 ]
