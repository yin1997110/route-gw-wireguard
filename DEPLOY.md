# 单机旁路由（WireGuard 策略路由 + DNS 分流）部署文档

> 实测环境：**J1900 小主机 · Ubuntu 26.04.1 LTS · 内核 7.0.x · 单网卡 `enp3s0`**（物理机，非容器）
> LAN `192.168.0.0/24` · 网关机 `192.168.0.125` · 上游路由器 `192.168.0.1`
> 对外只暴露一个 LAN 口：LAN 与 WAN 是同一个网卡，靠默认路由把上游当下一跳。

### 部署前必须替换的占位符

| 占位符 | 含义 | 出现位置 |
|---|---|---|
| `<GW_IP>` | 网关机在 LAN 的地址（如 `192.168.0.125`） | 本文示例、客户端设置 |
| `<LAN_IF>` | 接 LAN 的网卡名（如 `enp3s0`），脚本自动探测 | `00-listen.conf` 由 install.sh 生成 |
| `<UPSTREAM_GW>` | 上游路由器地址（如 `192.168.0.1`） | 默认路由，install.sh 不动它 |
| `<隧道内DNS>` | 隧道内可用的境外 DNS，用于解析被墙域名 | `GW_GFW_DNS` 环境变量 |
| `203.0.113.x` | RFC 5737 文档保留段，示例节点地址 | `wg0.conf` 示例 |
| `<PVE_HOST>` 等 | **已废弃**：本项目曾部署在 PVE/LXC 上，现已迁到单机，相关流程已从本文移除 | — |

---

## 一、架构概览

```
                 ┌────────────── 网关机（单网卡） ──────────────┐
   LAN 客户端 ────┤ enp3s0 <GW_IP>                                │
  (网关+DNS 都     │   ├─ 国内 IP 明细路由（~7400 条）→ enp3s0 直连 ──→ 上游路由器
   指向 <GW_IP>)   │   └─ 其余 → 表 51820 → wg0 ──隧道──→ 节点 ──→ Internet
                 │ dnsmasq :53（国内 223.5.5.5 / 被墙域名走隧道内 DNS）│
                 │ gw-admin :8080（面板，可选）                        │
                 └──────────────────────────────────────────────┘
```

| 项目 | 值 |
|---|---|
| 系统 | Ubuntu 26.04.1 LTS，内核 7.0.0 |
| 网卡 | `enp3s0`（唯一，LAN=WAN 同口） |
| LAN 地址 / 网段 | `<GW_IP>/24`，网段由 install.sh 按默认路由网卡现算 |
| 上游网关 | `<UPSTREAM_GW>`（主表默认路由，**本项目不动它**） |
| 隧道 | `wg0`，`10.14.0.2/16`，`Table = 51820`，`FwMark = 0xca6c`，MTU 1420 |
| DNS | dnsmasq，监听 `lo` + `<LAN_IF>`，上游 223.5.5.5 / 114.114.114.114 |
| 面板 | `gw-admin.service`，`/opt/gw-admin`，默认 `:8080` |

**关键点：主表默认路由永远指向 `<UPSTREAM_GW>`**，隧道只在表 51820 里接管非国内流量。
这样即使 `wg0` 挂了，国内访问和 SSH 管控也不会断，只是海外不通。

---

## 二、部署前准备

### 2.1 网络

```bash
ip -4 -br addr show          # 确认单网卡已有 LAN 地址
ip route show default        # 确认默认路由指向上游路由器
ping -c2 <UPSTREAM_GW>       # 通
```

- 不要手动加第二条默认路由，也不要改成 `0.0.0.0/0 dev wg0`（见 §3.2）。
- 若本机原本跑着 NetworkManager，`enp3s0` 用静态地址或 DHCP 都行，install.sh 只读不写网卡配置。

### 2.2 DNS 由本机接管（重要）

`install.sh` 会停用 `systemd-resolved`、把 `/etc/resolv.conf` 写成 `nameserver 127.0.0.1`。
这是**有意为之**：客户端的分流靠 dnsmasq 的按域名上游，若被 resolved 抢回 53 端口就全废。

```bash
systemctl is-active systemd-resolved   # 期望 inactive
ss -lntup | grep :53                   # 期望只有 dnsmasq
```

### 2.3 部署前备份（必做）

单机没有平台快照，回滚靠备份：

```bash
sudo tar czf /root/route-gw-before-$(date +%Y%m%d-%H%M).tar.gz \
  /etc/wireguard /etc/dnsmasq.conf /etc/dnsmasq.d /etc/cron.d/route-lists \
  /etc/sysctl.d/99-route-gw.conf /etc/systemd/system/dnsmasq.service.d /usr/local/bin
```

---

## 三、安装（网关）

把本仓库整个放到 `/opt/route-gw-deploy`，然后：

```bash
sudo GW_GFW_DNS='<隧道内DNS>' bash /opt/route-gw-deploy/install.sh
```

`install.sh` 做了 8 件事（幂等，可反复跑）：

1. **装包**：wireguard-tools、dnsmasq、curl、cron、iptables、iproute2。
   开装前等待 dpkg 锁最多 5 分钟（首启可能有残留交互式 apt 占锁）。
2. **投放配置**：`wg0.conf` → `/etc/wireguard/`（600），脚本 → `/usr/local/bin/`（755，装时去 CRLF），
   dnsmasq/cron/sysctl/apparmor/overlay 单元，以及 **DNS 自愈定时器**。
3. **sysctl**：`ip_forward=1`、`send_redirects=0`、`accept_redirects=0`、`rp_filter=2`
   （持久化于 `/etc/sysctl.d/99-route-gw.conf`；per-interface 值由 `wg-route-up.sh` 再校准）。
4. **接管 DNS**：停用 systemd-resolved，`/etc/resolv.conf` → `127.0.0.1`；
   `00-listen.conf` 按默认路由网卡生成，不写死接口/IP。
5. **拉起隧道**：`systemctl enable --now wg-quick@wg0`，PostUp 自动部署策略路由 + 动态 LAN NAT。
6. **首次拉数据源**：跑 `update-lists.sh`（github 走隧道下载，先有隧道后有列表）。
7. **自启**：dnsmasq、cron、`dnsmasq-healthcheck.timer` enable + start。
8. **打印状态快照**，见 §五 验证标准。

### 3.1 WireGuard 配置（`/etc/wireguard/wg0.conf`）

```ini
[Interface]
PrivateKey = <自己生成：wg genkey>
Address    = 10.14.0.2/16
MTU        = 1420
FwMark     = 0xca6c          # = 十进制 51820，WG 自身流量打标防死循环
Table      = 51820            # wg-quick 把 AllowedIPs 的两条 /1 写入表 51820，不动主表默认路由
PostUp     = /usr/local/bin/wg-route-up.sh
PostDown   = /usr/local/bin/wg-route-down.sh

[Peer]
PublicKey           = <你的对端公钥>
AllowedIPs          = 0.0.0.0/1, 128.0.0.0/1
Endpoint            = 203.0.113.9:51820
PersistentKeepalive = 25
```

> **没有 `DNS =` 行**：DNS 全归 dnsmasq，避免 wg-quick 改写 `/etc/resolv.conf`。
> `[Peer]` 只是初值，装上面板后由面板按节点池改写（切节点 = 改写本文件 + `wg syncconf`）。

### 3.2 策略路由原理

```
32764: from all lookup main suppress_prefixlength 0   # 查主表，忽略 0.0.0.0/0 默认路由
32765: not from all fwmark 0xca6c lookup 51820        # 未打标流量 → 表51820 → wg0
```

- 国内 IP：命中主表里 `wg-route-up.sh` 灌入的 ~7400 条 `/etc/china_ip_list.txt` 明细路由（最长前缀匹配），直连出口。
- 其余 IP：落到表 51820 的 `0.0.0.0/1 + 128.0.0.0/1`，走 `wg0`。
- **`AllowedIPs = 0.0.0.0/1, 128.0.0.0/1` 不是笔误**：两条 /1 合起来覆盖全部 IPv4，又不碰主表默认路由；
  配合 `Table = 51820` 和规则 32765，正好实现「只接管非国内流量」。
  写成 `0.0.0.0/0` 也能覆盖，但更依赖 `Table=51820` 始终生效；一旦 Table 丢失，wg-quick 会把默认路由
  写进主表顶掉 `<UPSTREAM_GW>`，风险更大。排障时不要先改这里。
- WG 自身流量带 `0xca6c` 标记跳过 32765，经 anti-loop `/32` 直连对端，防隧道套隧道。
- **32764/32765 是分流总开关**：缺任意一条，`wg0` 即使握手成功也完全不参与转发，表现为「国内正常、海外全挂」。
  面板 `health_loop` 每 3 秒自检并自动补回；`wg-route-up.sh` 也带重试和显式校验。
- **旁路由转发**：客户端包的目的地址仍是公网 IP，`ip_forward=1` 后按上面两条规则选路；
  从 LAN 口直连的做 `-s <LAN_NET> ! -d <LAN_NET> -o <LAN_IF> MASQUERADE`，
  从 `wg0` 出去的做 `-s <LAN_NET> ! -d <LAN_NET> -o wg0 MASQUERADE`。
  `LAN_NET` 每次启动按「默认路由网卡 + 地址前缀」现算，不写死。

### 3.3 DNS 分流（dnsmasq）

| 配置项 | 值 |
|--------|-----|
| 监听 | `lo` + 默认路由网卡（`bind-dynamic`；接口名由 `00-listen.conf` 跟随，不写死 IP） |
| 国内上游 | 223.5.5.5、114.114.114.114 |
| GFW 域名上游 | `/etc/default/route-gw` 的 `GW_GFW_DNS`（无标记流量 → 表 51820 → 走 wg0 出） |
| gfwlist 生成规则 | `/etc/dnsmasq.d/99-gfw.conf`（cron 每日覆盖重写） |
| 手工补充域名 | `/etc/dnsmasq.d/98-custom-domain.conf`（cron 不动它） |
| 面板下发域名 | `/etc/dnsmasq.d/97-panel.conf`（面板「分流规则」生成，勿手改） |

### 3.4 脚本一览（`/usr/local/bin/`）

| 脚本 | 触发 | 职责 |
|------|------|------|
| `wg-route-up.sh` | PostUp / 手动 / cron 联动 | 现算 LAN 网段、策略规则、anti-loop、灌国内路由、**动态 LAN NAT**、FORWARD、**TCPMSS 钳制**、sysctl、DNS 监听接口 |
| `wg-route-down.sh` | PostDown | 删国内路由、anti-loop、策略规则；摘除并删除 NAT/FORWARD/MSS 自定义链 |
| `update-lists.sh` | 每日 04:30 cron / 手动 | 拉 china_ip_list + gfwlist → 校验 → 原子替换 → 重启 dnsmasq（**带重启后校验**）→ 重灌路由 + 校准 NAT |
| `dnsmasq-healthcheck.sh` | `dnsmasq-healthcheck.timer` 每 5 分钟 | dnsmasq 不在/没监听 53 就重启并记 journal，失败则让单元 failed |
| `overlay-route-up.sh` / `-down.sh` | `route-gw-overlay.service` | ZeroTier/Tailscale 的 LAN→overlay NAT（独立链，见 OVERLAY.md） |

### 3.5 相对旧版本的关键修复（都实测踩过）

1. **anti-loop endpoint 解析**：旧版 PostUp/PostDown 用 `wg show wg0 endpoints` 取对端 IP，
   但 PostUp 时通常还没握手 → 拿到空串，anti-loop 路由**静默漏加**。现改为从 `wg0.conf` 静态解析。
2. **TCPMSS 黑洞修复（最重要）**：对端返回的 1460 字节 TCP 段带 DF 位，转发进 MTU 1420 的 `wg0` 时
   无法分片 → **TCP 握手成功、小请求正常、大响应（TLS ServerHello/页面/下载）全部超时**，
   而网关本机却正常（本机 socket 自动遵守 PMTU）。修复：
   `iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu`
   （已内置进 `wg-route-up.sh`）。
3. **update-lists 刷新条件**：旧版 `grep -q 'priority 32764'` 匹配不上 `ip rule show` 的真实格式
   （`32764:\t...`），每日更新后路由不会重灌。改为 `grep -q '32764:'`。
4. **上游网关自动探测**：不硬编码，从主表默认路由动态取。
5. **apt 锁等待** + `dpkg --configure -a` 兜底，模板首启残留不再阻断安装。
6. gfwlist 的 `@@` 例外规则**跳过**（例外域名仍走 WG DNS；需要精确直连的域名手工加进
   `98-custom-domain.conf` 并另行处理）。
7. **单臂旁路由修复**：
   - NAT 从写死网段改为按默认路由网卡现算的 `LAN_NET`；
   - 必须 `send_redirects=0`，否则同网段客户端会被 ICMP redirect 引到上游网关；
   - `bind-dynamic` + 生成的 `00-listen.conf` 让 DNS 跟随接口地址变化；
   - nft 后端的 `iptables` 不允许一条规则里出现两个 `-s`，NAT 规则已改成单 `-s`；
   - anti-loop endpoint 解析修正（旧 `awk -F'[ =:]'` 取到的是端口而不是 IP）。

### 3.6 本机 wireguard-tools 的两个坑（v1.0.20210914，面板换节点依赖）

1. **`wg syncconf wg0 -` 不支持**：这个版本把 `-` 当成文件名去 `fopen`，报
   `fopen: No such file or directory` 且返回码 1 —— 换 peer 看起来「执行了」其实什么都没发生，
   `wg0.conf` 与运行中的隧道从此永久分叉。可用写法：

   ```bash
   wg-quick strip wg0 > /tmp/x.conf && wg syncconf wg0 /tmp/x.conf   # 明文落盘，不推荐
   wg-quick strip wg0 | wg syncconf wg0 /dev/stdin                    # 面板采用：私钥不落盘
   ```

   `syncconf` 与 `down+up` 的区别：不重建接口、不动策略路由、下挂设备不断网。
2. **改对端入口必须带 peer**：`wg set wg0 peer <_pubkey> endpoint <ip:port>`；
   写成 `wg set wg0 endpoint <ip:port>` 会报 `Invalid argument: endpoint`。
3. 手工把在线 peer 的入口指向黑洞，约 10 秒内会被 WireGuard 的**入口漫游**自动纠正回来
   （旧对端还在发认证包）。要模拟「真死了」得用 iptables 双向丢 UDP：
   `iptables -I INPUT 1 -s <对端IP> -p udp --sport 51820 -j DROP` + 对应 OUTPUT 规则，测完 `-D` 删掉。
4. **节点状态/延迟来自数据源，不是本机探测**：数据源服务器自己会扫描节点，面板直接用它的
   `alive`/`ping`/`health`。同一城市里仍可能存在 ping 正常但 WG 端口不握手的节点，
   所以「能不能切」最终由切换时的真实握手决定。
5. **本机不再逐节点 ping/TCP 探测**：旧版本每 5 秒并发 40 个 ICMP，导致部分入口不响应 ICMP、
   主路由/ISP 限速、矩阵同步把 `fault` 洗回 `online` 后反复写 `node_down`。现在只保留：
   - 当前隧道的 `wg` 握手年龄 + 隧道内实测（约 15 秒一次）；
   - 节点状态/延迟完全取自数据源扫描；
   - `auto_switch` 必须连续 **2 次**隧道 100% 丢包（约 30s）且最近握手 >120s；
   - 切换目标由真实握手验证，失败自动回滚/换下一个候选。

   56 字节的 ICMP echo 不会触发 1500/1492 的 MTU 分片；`ping -M do -s 1400` 从 WG 里失败，
   是 `wg0` 自身 MTU 1420 导致的，不是主路由 MTU。主路由 MTU 只影响大包，已有 TCPMSS 钳制处理。

### 3.7 Ubuntu 26.04 的 wg-quick AppArmor

Ubuntu 26.04 起自带 `/etc/apparmor.d/wg-quick`，默认禁止 PostUp/PostDown 执行
`/usr/local/bin/*.sh`，现象是 `wg-quick up` 在 PostUp 处报：

```text
wg-quick: /usr/local/bin/wg-route-up.sh: Permission denied
audit: apparmor="DENIED" operation="exec" profile="wg-quick" name="/usr/local/bin/wg-route-up.sh"
```

只放行两个钩子即可（不要整体禁用 AppArmor）：

```bash
sudo install -d /etc/apparmor.d/local
sudo tee /etc/apparmor.d/local/wg-quick >/dev/null <<'EOF'
/usr/local/bin/wg-route-up.sh rux,
/usr/local/bin/wg-route-down.sh rux,
EOF
sudo apparmor_parser -r /etc/apparmor.d/wg-quick
```

`install.sh` 检测到 `/etc/apparmor.d/wg-quick` 时会自动合并这段 local override；
仓库的 `files/etc/apparmor.d/local/wg-quick` 就是该文件。

> 路由灌入/删除用 `ip -batch`：J1900 上 PostUp 约 2 秒，`systemctl restart wg-quick@wg0` 约 4 秒。

---

## 四、同网段客户端接入

不需要装任何脚本，也不需要改路由表——客户端只要做两件事：

1. **默认网关** = `<GW_IP>`
2. **DNS** = `<GW_IP>`

```bash
# Linux 客户端示例（NetworkManager）
nmcli con mod "<连接名>" ipv4.gateway <GW_IP> ipv4.dns <GW_IP> ipv4.ignore-auto-dns yes
nmcli con up "<连接名>"
```

> 关键点：**两个都必须是 `<GW_IP>`**。只改网关不改 DNS，域名层分流（gfwlist）就失效；
> 只改 DNS 不改网关，流量根本不经过本机。
>
> 本机不是客户端所在网段的网关时（跨网段），下一跳不可达，需要把网关机接到该网段
> 或建 GRE/VXLAN 隧道——本方案不做。

---

## 五、部署后验证（标准结果）

```bash
# --- 网关机上 ---
systemctl is-active wg-quick@wg0 dnsmasq cron dnsmasq-healthcheck.timer   # 全 active
wg show wg0 | grep handshake                       # latest handshake: xx 秒前（必须新鲜）
ip rule show | grep -E '32764|32765'               # 两条都在
ip route | wc -l                                    # ~7460+（含国内明细路由）
ip route show table 51820                           # 0.0.0.0/1 和 128.0.0.0/1 dev wg0
iptables -t mangle -S ROUTE_GW_MSS                  # 含 TCPMSS --clamp-mss-to-pmtu
iptables -t nat -S ROUTE_GW_NAT                     # 两条 MASQUERADE：-o <LAN_IF> 与 -o wg0
wc -l /etc/china_ip_list.txt                        # > 5000（实测 7456）
grep -c '^server=' /etc/dnsmasq.d/99-gfw.conf       # > 1000（实测 4376）
ip -4 -br addr show <LAN_IF>; ip route show default # 确认 LAN 地址/上游网关
cat /etc/dnsmasq.d/00-listen.conf                   # interface=lo + 默认路由网卡
ss -lntup | grep :53                                # 只有 dnsmasq

# 分流矩阵（网关机与同网段客户端上分别执行，结果应一致）
curl -s -m 15 http://ip.3322.net                            # 国内出口 IP → 直连生效
curl -s -m 15 https://ipinfo.io/ip                          # 节点出口 IP → 隧道生效
curl -skL -m 25 -o /dev/null -w '%{http_code}\n' https://github.com   # 200 → 域名层生效
getent hosts baidu.com                                      # 国内 IP → 国内 DNS 视角
getent hosts google.com                                     # 海外 IP → 隧道 DNS 视角
```

重启持久化验证：`sudo reboot && sleep 40` 后重跑上面矩阵。
实测 J1900 重启后 `wg-quick@wg0`、`dnsmasq`、`dnsmasq-healthcheck.timer`、`gw-admin` 全部自恢复。

> 装了管理面板之后，这节矩阵仍然照用（面板不改网络行为）；面板自身的自检见
> **WEB-DEPLOY.md §九**。两边对不上时以这里的命令行为准——面板只是这些状态的读取器。

---

## 六、运维速查

```bash
# 隧道
systemctl restart wg-quick@wg0          # 重启会重跑 PostUp 全套
journalctl -u wg-quick@wg0 --no-pager | tail -30

# 钩子日志（脚本里 logger 打的）
journalctl -t wg-up -t wg-down -t route-update -t dns-health --no-pager | tail -40

# 数据源
/usr/local/bin/update-lists.sh          # 手动更新
tail -50 /var/log/update-lists.log      # cron 日志（04:30）

# DNS
journalctl -u dnsmasq.service -f        # 查询日志（log-queries 是启动期选项，改了要 restart）
journalctl -t dns-health --no-pager     # 自愈记录

# 排错一把梭
wg show wg0; ip rule show; ip route | head; ip route show table 51820
iptables -t nat -S POSTROUTING; sysctl net.ipv4.ip_forward
bash /opt/route-gw-deploy/tools/peer-check.sh    # 0=文件与隧道一致 1=分叉
```

---

## 七、故障处理

| 症状 | 排查 |
|------|------|
| 全网域名都解析失败（IP 直连正常） | **先看 `systemctl is-active dnsmasq` 和 `ss -lntup \| grep :53`**。dnsmasq 挂了 = 全内网 DNS 断，见下面专项 |
| 同网段主机完全不通 | `ping <GW_IP>` → `iptables -t nat -S ROUTE_GW_NAT`（两条 MASQUERADE）→ `ip_forward=1`；确认客户端网关和 DNS 都指向本机 |
| 能上国内、代理全不生效 | 先看 `ip rule show \| grep -E '32764\|32765'`：缺规则时 `wg0` 有握手也不会被使用；面板 3 秒内自动补回，也可手动 `/usr/local/bin/wg-route-up.sh` |
| 切换节点后突然海外全挂 | 先确认 `ip rule` 两条规则是否还在；`AllowedIPs` 保持 `0.0.0.0/1,128.0.0.0/1`，不要改成 `0.0.0.0/0` 来「修」 |
| 客户端能通但被「绕过」 | `cat /proc/sys/net/ipv4/conf/<LAN_IF>/send_redirects` 必须为 0 |
| 小网页能开、稍大的页面/下载卡死 | TCPMSS 规则丢失 → 见 §3.5-2，跑 `wg-route-up.sh` 即恢复 |
| WG 无握手 | `journalctl -u wg-quick@wg0`；`tools/peer-check.sh` 看当前对端是谁，再确认本机能直连**那个** `IP:51820`（UDP）、对端密钥/端口配对 |
| 数据源更新失败 | 多为隧道当时未恢复（下载走隧道）；隧道恢复后手动跑 `update-lists.sh` |
| 面板显示「当前节点」与实际隧道对不上 | `tools/peer-check.sh` 确认分叉 → `python3 /opt/gw-admin/gw_server.py --restore` 以隧道为准重写配置（不动在跑的 peer） |
| 节点 ping 得通却切不过去 | 该节点 WG 端口不通（§3.6-4）；面板会 8s 握手超时后自动回滚，属正常保护 |
| apt 卡 "Could not get lock" | 残留交互式 apt：`ps aux \| grep apt` 找到后 kill，再 `dpkg --configure -a` |

### 专项：2026-11-05 全内网 DNS 静默中断（真事故，务必读完）

**现象**：早上开始所有设备「能连上但网页全打不开 / 像梯子失效」，而 WireGuard 握手一直正常、
`wg show` 有流量、路由规则也都在。

**根因链条**：

| 时间 | 事件 |
|---|---|
| 11-04 19:58 | 有人 `apt install -y docker.io docker-compose`；`docker.io` 的 **Recommends** 带进 `ubuntu-fan` |
| 同上 | `ubuntu-fan` 投放 `/etc/dnsmasq.d/ubuntu-fan`，内容含 **`bind-interfaces`** |
| — | 与本项目 `/etc/dnsmasq.conf` 的 **`bind-dynamic`** 互斥；因 dnsmasq 还在跑（读旧配置），未暴露 |
| **11-05 04:30** | 每日 `update-lists.sh` 更新 gfwlist 后 `systemctl restart dnsmasq` → `cannot set --bind-interfaces and --bind-dynamic` → **启动失败** |
| 04:30–09:00 | `127.0.0.1:53` 无人监听，全内网 DNS 死掉，且脚本当时没有重启后校验，没人发现 |

**为什么容易误判**：`dnsmasq --test` 只做语法检查，对这个冲突返回 `syntax check OK`；
而 `wg show` 一切正常，很自然会怀疑隧道。**判断顺序应该是：先查 53 端口有没有人监听。**

**修复（已固化进本仓库）**：

```bash
# 1) 找出并清掉冲突源（ubuntu-fan 只是 docker 的 Recommends，可以单独移除）
apt purge -y ubuntu-fan
# 或者保留包、只注释冲突行
sed -i 's|^bind-interfaces|# bind-interfaces|' /etc/dnsmasq.d/ubuntu-fan

# 2) 重启并确认
systemctl restart dnsmasq && ss -lntu | grep 127.0.0.1:53
```

**防复发（三重）**：

1. `update-lists.sh` 重启 dnsmasq 后**校验**并记日志（`dnsmasq 重启校验通过` / `严重错误`）；
2. `dnsmasq-healthcheck.timer` 每 5 分钟检查「进程 active + 53 在听」，异常自动重启并记
   `journalctl -t dns-health`，仍失败则单元 failed（`systemctl --failed` 可见）；
3. `install.sh` 若发现 `ubuntu-fan` 的 `bind-interfaces` 会自动注释掉。

> 装 docker 时若不需要 fan 网络，用 `apt install --no-install-recommends docker.io`
> 可以不再把 `ubuntu-fan` 拉进来。

---

## 八、已知限制

- **仅 IPv4**：策略路由/明细路由都只覆盖 IPv4；若上游给了 IPv6，海外站点 AAAA 会原生直连出泄漏。
- **gfwlist 只管域名**：直接用 IP 访问、或客户端自带 DoH/硬编码 DNS 的应用不受 DNS 层管辖
  （仍受 IP 层国内列表约束）。
- **`@@` 例外规则跳过**：gfwlist 里标记直连的域名仍走隧道 DNS 解析，但解析出的若为国内 IP
  会被 IP 层拉回直连，实际影响小。
- `198.51.100.53` 是占位用的境外 DNS，部署时用 `GW_GFW_DNS=<真实地址>` 覆盖；
  不配置就会把 gfw 域名指到一个不可用地址。
- **只服务同一二层 LAN**：不同网段的主机不能直接把本机 LAN IP 写成默认网关（下一跳不可达）。
- `/var/log/update-lists.log` 未配 logrotate，长期跑注意（可加 `/etc/logrotate.d/route-lists`）。
- `docker0` / 容器网络与本方案无关；装 docker 会额外插入 DOCKER 链，不影响分流规则。

---

## 九、目录清单

```
route-gw-deploy/
├── README.md                     ← 总入口：目录导航、部署顺序、安全须知
├── DEPLOY.md                     ← 网关部署（本文档）
├── WEB-DEPLOY.md                 ← 管理面板部署与运维
├── OVERLAY.md                    ← LAN → ZeroTier/Tailscale NAT
├── MATRIX-FORMAT.md              ← data.js 节点源格式
├── install.sh                    ← 一键安装网关
├── install-web.sh                ← 一键安装管理面板
├── install-zerotier.sh           ← 安装/加入 ZeroTier 并启用 overlay NAT
├── files/
│   ├── etc/wireguard/wg0.conf            ⚠示例值，真实私钥自填，权限 600 投放
│   ├── etc/dnsmasq.conf                  ⚠含 bind-dynamic（不要再加 bind-interfaces）
│   ├── etc/dnsmasq.d/{00-listen,98-custom-domain}.conf
│   ├── etc/cron.d/route-lists            ← 每日 04:30 跑 update-lists.sh
│   ├── etc/sysctl.d/99-route-gw.conf
│   ├── etc/apparmor.d/local/wg-quick     ← Ubuntu 26.04+ 放行钩子
│   ├── etc/systemd/system/dnsmasq.service.d/override.conf
│   ├── etc/systemd/system/route-gw-overlay.service
│   ├── etc/systemd/system/dnsmasq-healthcheck.{service,timer}
│   └── usr/local/bin/{wg-route-up,wg-route-down,update-lists,
│                      overlay-route-up,overlay-route-down,dnsmasq-healthcheck}.sh
├── tools/peer-check.sh           ← 核对 wg0.conf 与真实隧道是否分叉
└── web/                          ← 管理面板（见 web/app/CONTRACT.md）
```
