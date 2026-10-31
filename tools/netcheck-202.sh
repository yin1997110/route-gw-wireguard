#!/bin/bash
# netcheck-202.sh — CT202 客户端完整网络自检
set -u
pass(){ echo "  [PASS] $*"; }
fail(){ echo "  [FAIL] $*"; }

echo "===== 0. 基本信息 ====="
echo "IPv4:  $(ip -4 a show scope global | awk '/inet/{print $2}')"
echo "route: $(ip route | tr '\n' ' ')"
echo "DNS:   $(grep -v '^#' /etc/resolv.conf | grep nameserver | tr '\n' ' ')"
IPv6=$(ip -6 a show scope global | grep -c 'inet6' || true)
[ "$IPv6" = "0" ] && pass "无全局 IPv6 地址（无 v6 泄漏面）" || fail "存在 IPv6 全局地址 $IPv6 条，可能绕过 IPv4 分流"
date
timedatectl show -p NTPSynchronized --value | grep -q yes && pass "时钟已同步(TLS 前提)" || fail "时钟未同步"

echo "===== 1. 内网/网关 ====="
if ping -c 10 -W 1 192.168.99.1 >/dev/null 2>&1; then
  pass "网关 201 可达: $(ping -c 10 -W 1 192.168.99.1 2>/dev/null | tail -2 | head -1)"
else fail "ping 网关失败"; fi

echo "===== 2. DNS 双视角 ====="
DOM_RESOLVED=1; OVS_RESOLVED=1
for d in baidu.com qq.com taobao.com jd.com; do
  ip=$(getent hosts "$d" | awk '{print $1; exit}')
  echo "  $d -> ${ip:-FAIL}"
  [ -z "$ip" ] && DOM_RESOLVED=0
done
for d in google.com youtube.com github.com twitter.com instagram.com; do
  ip=$(getent hosts "$d" | awk '{print $1; exit}')
  echo "  $d -> ${ip:-FAIL}"
  [ -z "$ip" ] && OVS_RESOLVED=0
done
[ $DOM_RESOLVED = 1 ] && pass "国内域名解析正常" || fail "国内域名解析异常"
[ $OVS_RESOLVED = 1 ] && pass "GFW 域名解析正常(经 WG DNS)" || fail "GFW 域名解析异常"

echo "===== 3. ICMP 分流（IP 层，不经 DNS） ====="
R1=$(ping -c 5 -W 2 223.5.5.5 2>/dev/null | tail -1 | awk '{print $4}')
echo "  国内 223.5.5.5 loss=$R1"
[ "${R1%\'*}" = "0" ] && pass "国内 ICMP 直连" || fail "国内 ICMP 丢包"
R2=$(ping -c 5 -W 3 1.1.1.1 2>/dev/null | tail -1 | awk '{print $4}')
echo "  海外 1.1.1.1 loss=$R2 (经隧道)"
[ "${R2%\'*}" = "0" ] && pass "海外 ICMP 走隧道" || fail "海外 ICMP 丢包"

echo "===== 4. 国内 HTTPS 与耗时 ====="
for u in https://www.baidu.com https://www.qq.com http://myip.ipip.net; do
  out=$(curl -s -m 15 -o /dev/null -w "code=%{http_code} dns=%{time_namelookup} conn=%{time_connect} tls=%{time_appconnect} total=%{time_total}" "$u" 2>/dev/null) && echo "  $u -> $out" || fail "$u"
done

echo "===== 5. 海外 HTTPS 与耗时 ====="
for u in https://www.google.com https://www.youtube.com https://github.com https://x.com https://raw.githubusercontent.com; do
  out=$(curl -sIL -m 20 -o /dev/null -w "code=%{http_code} dns=%{time_namelookup} conn=%{time_connect} tls=%{time_appconnect} total=%{time_total}" "$u" 2>/dev/null) && echo "  $u -> $out" || fail "$u (rc=$?)"
done

echo "===== 6. 出口 IP 一致性 ====="
DOM=$(curl -s -m 15 http://myip.ipip.net 2>/dev/null | grep -o '[0-9.]\{7,\}' | head -1)
echo "  国内出口: ${DOM:-FAIL}"
for i in 1 2 3; do
  O1=$(curl -sk -m 15 https://1.1.1.1/cdn-cgi/trace 2>/dev/null | awk -F= '/^ip=/{print $2}')
  echo "  海外出口 try$i: ${O1:-FAIL}"
done

echo "===== 7. 大文件下载（隧道分片稳定性，3 轮） ====="
for i in 1 2 3; do
  curl -sk -m 40 -o /dev/null -w "  round$i: %{size_download}B %{speed_download}B/s in %{time_total}s rc=" 'https://speed.cloudflare.com/__down?bytes=5000000' 2>/dev/null; echo $?
done

echo "===== 8. 同一连接多请求复用（隧道长会话） ====="
curl -s -m 25 -o /dev/null -w "  conn1=%{num_connects} req1=%{response_code}\n" https://github.com 'https://api.github.com/zen' 2>/dev/null \
  && pass "keepalive 多请求复用正常" || fail "keepalive 测试"

echo "===== 9. 连续 10 轮抽样稳定性 ====="
okc=0; okg=0
for i in $(seq 1 10); do
  curl -s -m 10 -o /dev/null http://myip.ipip.net && okc=$((okc+1))
  curl -sk -m 12 -o /dev/null https://www.google.com && okg=$((okg+1))
done
echo "  国内 $okc/10, 海外 $okg/10"
[ $okc -ge 9 ] && [ $okg -ge 9 ] && pass "抽样稳定性达标" || fail "抽样不稳定"

echo "===== 10. 边界项 ====="
# 单标签/无效域名行为
getent hosts nonexistent.invalid >/dev/null 2>&1 && fail "NXDOMAIN 处理" || pass "无效域名正确拒绝"
# UDP 53 直接查询
python3 - <<'PYEOF' 2>/dev/null && pass "UDP53 手工报文查询" || fail "UDP53 手工查询"
import socket,struct,random
rid=random.randint(0,65535)
q=struct.pack('!H',rid)+b'\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x06google\x03com\x00\x00\x01\x00\x01'
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(5)
s.sendto(q,('192.168.99.1',53));d,_=s.recvfrom(512)
assert d[0:2]==struct.pack('!H',rid) and d[6:8]!=b'\x00\x00'
PYEOF
echo "===== 完成 ====="
