# 把 CT201 的整套配置迁移到一台原生 Ubuntu 主机

本文记录把 LXC 201（route-gw）完整搬迁到一台原生 Ubuntu 机器的步骤。
目标机示例：`192.168.0.125`（Ubuntu 26.04，单网卡 `enp3s0`，网关 `192.168.0.1`）。
迁移后它也是**同网段单臂旁路由**：同网段主机把网关 + DNS 指向它的 LAN 地址即可。

> ⚠️ 同一个 WireGuard 私钥**不能在两台机器上同时跑**：服务端只认一个 peer，
> 两台同时 keepalive 会让 endpoint 来回漫游。迁移前必须先停掉旧机：
>
> ```bash
> # 在 PVE 上
> pct exec 201 -- systemctl stop gw-admin wg-quick@wg0
> pct exec 201 -- systemctl disable gw-admin wg-quick@wg0
> ```
>
> 旧机的 dnsmasq 可以继续留着给原网段做 DNS；但隧道和面板必须停，避免和新机抢同一个 peer。

---

## 1. 在旧机（CT201）打包

只打配置/数据，不打系统文件、日志和私钥以外的机密：

```bash
# 在 CT201 内以 root 执行
tar czf /tmp/ct201-migrate.tar.gz -C / \
  etc/wireguard/wg0.conf \
  etc/dnsmasq.conf etc/dnsmasq.d \
  etc/china_ip_list.txt \
  etc/cron.d/route-lists \
  etc/sysctl.d/99-route-gw.conf \
  etc/default/route-gw \
  etc/systemd/system/gw-admin.service \
  etc/systemd/system/gw-admin.service.d \
  etc/systemd/system/dnsmasq.service.d/override.conf \
  opt/gw-admin \
  usr/local/bin/wg-route-up.sh \
  usr/local/bin/wg-route-down.sh \
  usr/local/bin/update-lists.sh
```

把包取到 PVE 再传给目标机（或直接从 CT201 `scp` 到目标机）：

```bash
# PVE 上
pct pull 201 /tmp/ct201-migrate.tar.gz /tmp/ct201-migrate.tar.gz
scp /tmp/ct201-migrate.tar.gz ywl@192.168.0.125:/tmp/
```

> 包里有 `/etc/wireguard/wg0.conf` 真实私钥和面板 `data/credentials.json`。
> 传输走 SSH，落地后 `chmod 600`，不要提交回仓库。

## 2. 目标机装依赖

```bash
sudo apt-get update
sudo apt-get install -y wireguard-tools dnsmasq curl ca-certificates cron iptables iproute2
```

## 3. 停掉 systemd-resolved 并解包

```bash
sudo systemctl disable --now systemd-resolved
sudo systemctl stop dnsmasq 2>/dev/null || true

sudo tar xzf /tmp/ct201-migrate.tar.gz -C /
sudo rm -rf /opt/gw-admin/__pycache__ /opt/gw-admin/gw_server.py.bak /opt/gw-admin/backup

sudo install -d -m 700 /etc/wireguard
sudo chmod 600 /etc/wireguard/wg0.conf
sudo chmod 755 /usr/local/bin/wg-route-up.sh /usr/local/bin/wg-route-down.sh /usr/local/bin/update-lists.sh
sudo chown -R root:root /opt/gw-admin

# DNS 指向本机 dnsmasq；PVE 托管的 CT 不要这样手改，原生机可以
sudo rm -f /etc/resolv.conf
echo 'nameserver 127.0.0.1' | sudo tee /etc/resolv.conf

sudo systemctl daemon-reload
sudo sysctl --system
sudo dnsmasq --test
```

## 4. Ubuntu 26.04 的 wg-quick AppArmor 坑

Ubuntu 26.04 自带 `/etc/apparmor.d/wg-quick`，默认**拒绝** PostUp/PostDown 执行
`/usr/local/bin/wg-route-up.sh`，日志表现为：

```text
wg-quick: /usr/local/bin/wg-route-up.sh: Permission denied
audit: apparmor="DENIED" operation="exec" profile="wg-quick" name="/usr/local/bin/wg-route-up.sh"
```

用 local override 只放行两个钩子（不要让整个 wg-quick 变 unconfined）：

```bash
sudo install -d /etc/apparmor.d/local
sudo tee /etc/apparmor.d/local/wg-quick >/dev/null <<'EOF'
/usr/local/bin/wg-route-up.sh rux,
/usr/local/bin/wg-route-down.sh rux,
EOF
sudo apparmor_parser -r /etc/apparmor.d/wg-quick
```

仓库里的 `files/etc/apparmor.d/local/wg-quick` 就是这个文件，`install.sh` 会自动合并。

## 5. 启动顺序

```bash
sudo systemctl enable --now wg-quick@wg0     # PostUp 会算 LAN 网段、灌路由、建 NAT
sudo systemctl enable --now dnsmasq
sudo systemctl enable --now cron
sudo systemctl enable --now gw-admin
```

`wg-quick` 启动时会打印：

```text
[wg-up] 旁路由模式: LAN=enp3s0 192.168.0.125/24 net=192.168.0.0/24, 上游=enp3s0 via 192.168.0.1 ...
[wg-up] 国内直连路由: 7456 条
[wg-up] 旁路由分流部署完成 (LAN 192.168.0.0/24, 网关 192.168.0.125)
```

> `wg-route-up.sh` 已用 `ip -batch` 灌 7400+ 条路由，J1900 上从 ~49 秒降到 ~2 秒；
> `wg-route-down.sh` 同样批量删除，`systemctl restart wg-quick@wg0` 约 4 秒。

## 6. 验收（目标机上）

```bash
# 隧道与策略
systemctl is-active wg-quick@wg0 dnsmasq gw-admin cron
wg show wg0 | grep -E 'handshake|endpoint'
ip rule show | grep -E '32764|32765'
iptables -t nat -S ROUTE_GW_NAT
ip route show table main | wc -l          # ~7460

# 本机分流
curl -4 -s https://api.ipify.org          # WG 出口 IP
curl -4 -s -o /dev/null -w '%{http_code}\n' https://www.baidu.com   # 200
dig +short @127.0.0.1 google.com          # 92.x（隧道 DNS 视角）
dig +short @127.0.0.1 baidu.com           # 国内 IP

# 面板
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/
```

同网段客户端把**默认网关**和 **DNS** 都改成目标机 LAN 地址（如 `192.168.0.125`），
然后在客户端上跑 `tools/netcheck-202.sh` 或直接：

```bash
curl -4 -s https://api.ipify.org          # 应为 WG 出口
curl -4 -s -o /dev/null -w '%{http_code}\n' https://www.baidu.com
```

## 7. 跨网段客户端限制（CT202 这类）

CT202 在 `192.168.1.0/24`（1 网段），J1900 在 `192.168.0.0/24`（0 网段），两者**不在同一二层**。
把 CT202 的默认网关直接写成 `192.168.0.125` 会失败：下一跳不在同网段，内核无法 ARP，表现为直接断网。
`onlink` 也不行，因为跨网段时帧仍然只能发给 1 网段的网关，IP 目的地址不会自动转到 J1900。

因此：

- 要测 J1900 的旁路由，**客户端必须在 0 网段**：把网关和 DNS 都设为 `192.168.0.125`。
- 如果一定要让 1 网段的 CT202 走 J1900，只有三条路：
  1. 把 J1900 的网线接到 1 网段，J1900 改成 `192.168.1.x`（会失去原来的 0 网段客户端）；
  2. 给 PVE 增加一块能到 0 网段的物理网卡/网桥，把 CT202 改到 `192.168.0.x`；
  3. 在 PVE 和 J1900 之间建 GRE/VXLAN 隧道，把 CT202 的 L2/L3 接到 J1900。
- 本次没有改 CT202 的网关，避免把它从 1 网段弄断；测试用的是 J1900 上的 netns
  `192.168.0.250`，走的是真实 0.x 客户端的转发/NAT 路径。

完整测试数据见 **TEST-REPORT.md**（Docker Registry 拉取、50/100MB 下载、强制重启恢复）。

## 8. 迁移后的注意事项

- **静态地址**：目标机若用 DHCP，建议在 `192.168.0.1` 上给 `192.168.0.125` 做 DHCP 静态绑定，
  否则租约变化会让所有客户端的网关/DNS 失效。本文没有直接改 netplan，避免远程失联。
- **IPv6 泄漏**：本方案只分流 IPv4。目标机/客户端若有 IPv6 默认路由，IPv6 站点仍会直连上游，
  IPv6 能力强的应用可能绕过隧道。不需要 IPv6 时可在目标机加：
  `net.ipv6.conf.all.disable_ipv6=1`（客户端仍需自行处理）。
- **面板密码/数据**：`/opt/gw-admin/data` 原样迁过来，节点池、规则、订阅、事件都还在；
  登录地址变成 `http://192.168.0.125:8080`。如果旧密码已经忘记，用
  `sudo python3 /opt/gw-admin/gw_server.py --set-password admin '新密码'` 重置，
  再 `sudo systemctl restart gw-admin`（面板只存 PBKDF2 哈希，无法反查明文）。
- **旧机回退**：先停新机 `wg-quick@wg0`，再在旧机
  `systemctl enable --now wg-quick@wg0 gw-admin`，否则两台会抢同一个 peer。
- **cron**：`/etc/cron.d/route-lists` 每天 04:30 跑 `update-lists.sh`，它会重新生成
  `/etc/dnsmasq.d/99-gfw.conf` 并调用 `wg-route-up.sh`；`GW_GFW_DNS` 从 `/etc/default/route-gw` 读。
- **AppArmor 持久化**：`/etc/apparmor.d/local/wg-quick` 在重启后仍由 apparmor 加载，已实测重启后
  `wg-quick` 能正常执行 PostUp。
- **Go 工具优先 IPv6**：目标机若有全局 IPv6，`skopeo`/`docker` 等 Go 程序可能先连 IPv6 直连并被 reset。
  可在 `/etc/gai.conf` 加一行 `precedence ::ffff:0:0/96 100`，测试时配合
  `GODEBUG=netdns=cgo`；本方案只分流 IPv4，IPv6 泄漏仍需另行处理。
