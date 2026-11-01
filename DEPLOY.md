# CT 201 / CT 202 分流网关部署文档

> 日期: 2026-10-31 | 版本: v3.1（同网段单臂旁路由版）
> 环境: PVE 9.1.1（宿主机 <PVE_HOST>），LXC 201/202，Ubuntu 24.04，非特权容器
> 本目录即完整部署包，可在新环境按本文一步步重建。
> 管理面板（Web）见同目录 **WEB-DEPLOY.md**；先看 **README.md** 了解本目录怎么组织。
>
> **v3.1 的关键变化：201 只保留一块 LAN 网卡（eth0），不再需要 eth1/vmbr2 内网。**
> 同网段任意主机（202、手机、PC、其它 LXC）只要把「默认网关 + DNS」都指向 201 的
> LAN 地址，就自动跟随分流。脚本里不再写死 LAN IP/网段：每次启动从默认路由和网卡
> 地址现算，换网络/换 IP 后重启隧道即可自动跟随。
> ⚠️ 本包内的 `wg0.conf` 是**示例值**（私钥留空、对端用占位符）。真实私钥只存在于你自己那台机器上，
> 永远不要写回本仓库、不要提交、不要贴进聊天工具。

### 部署前必须替换的占位符

公开仓库里不保留任何可直接使用的接入信息，落地前先换成你自己的值：

| 位置 | 当前占位值 | 换成 |
|------|-----------|------|
| `files/etc/wireguard/wg0.conf` `PrivateKey` / `PublicKey` / `Endpoint` | `<wg genkey 生成…>` / `203.0.113.9:51820` | 订阅给你的私钥、对端公钥与入口地址 |
| `files/etc/wireguard/wg0.conf` `Address` | `10.14.0.2/16` | 订阅分配给你的隧道地址 |
| `/etc/default/route-gw` 的 `GW_GFW_DNS`（部署时由 `GW_GFW_DNS=... bash install.sh` 生成，仓库里不含） | `198.51.100.53` | WG 出口视角的境外 DNS |
| `files/etc/dnsmasq.d/98-custom-domain.conf` 每行末尾 | `198.51.100.53` | 同上（install.sh 会按 `GW_GFW_DNS` 自动替换） |
| `web/server/gw_server.py` `G["GFW_DNS"]` / `D["MATRIX"]` | `198.51.100.53` / `https://matrix.example.com:3333/data.js` | 见 WEB-DEPLOY.md：推荐用 systemd drop-in `GW_GFW_DNS` / `GW_MATRIX_URL` 覆盖，不改代码 |
| PVE / LXC 地址、root 密码 | `<PVE_HOST>` 等 | 只写进你自己的密码管理器，别提交 |
| 面板管理员密码 | 首次登录时设置 | 见 WEB-DEPLOY.md 的初始化步骤 |

`198.51.100.0/24`、`203.0.113.0/24` 是 RFC 5737 文档保留段，故意用作占位：它们不会真的解析出结果，
照抄部署会得到"域名解析能通但都落在占位上游"的现象，所以务必先替换。

---

## 一、架构概览

```
同网段主机 (202/手机/PC ...)
   │  网关 = 201 LAN IP，DNS = 201 LAN IP
   ▼
┌──────────────────── LXC 201（单臂旁路由，只有 eth0）────────────────────┐
│  eth0 192.168.1.212/24  ← 同网段 LAN，也是 WAN 出口                     │
│                                                                        │
│  国内目标 ──→ 主表国内明细路由 ──→ 上游网关 192.168.1.1 ──→ Internet     │
│  其余目标 ──→ 表 51820 ──→ wg0 (10.14.0.2/16) ──→ 海外 Internet         │
│                                                                        │
│  POSTROUTING: -s 192.168.1.0/24 ! -d 192.168.1.0/24 -o eth0/wg0 MASQUERADE
│  同一网卡进出: send_redirects=0、ip_forward=1、rp_filter=2               │
└────────────────────────────────────────────────────────────────────────┘
```

- **LXC 201 (router)**：分流网关 + DNS，**单臂**接在 vmbr0。国内 IP 走 eth0 直连，其余走 wg0；dnsmasq 按 gfwlist 域名把海外域名解析到 WG 出口视角。
- **LXC 202 (client)**：同样接 vmbr0 的 192.168.1.0/24，`gw=192.168.1.212`、`nameserver=192.168.1.212`，不需要第二块网卡。
- 分流三要素：**策略路由规则 + 国内 IP 明细路由（IP 层）+ gfwlist 域名 DNS 劫持（域名层）**，缺一不可。
- **关键差别**：客户端和上游网关在同一网段，客户端把包发给 201 的 MAC，201 转发后再从同一块 eth0 出去。
  因此 NAT 必须按 LAN 网段做（直连 SNAT 成 201、隧道 SNAT 成 10.14.0.2），并且必须关掉 ICMP redirect，
  否则客户端会被"重定向"到 192.168.1.1 而绕过 201。

### 设备清单

| 项目 | LXC 201 router | LXC 202 client |
|------|----------------|----------------|
| VMID | 201 | 202 |
| 用途 | 分流网关 + DNS | 测试节点 |
| eth0 | <GW_IP>/24（vmbr0，LAN=WAN 同一个口） | 192.168.1.202/24（vmbr0 同网段） |
| eth1 | —（v3.1 已删除） | — |
| wg0 | 10.14.0.2/16 | — |
| 默认网关 | 192.168.1.1（PVE 侧配置，保持不动） | 192.168.1.212（201） |
| DNS | 127.0.0.1（本机 dnsmasq） | 192.168.1.212（201 dnsmasq） |
| 规格 | 1C / 512MB | 1C / 512MB |
| 密码 | root 密码见密码管理器（部署时用 `PVE_PW` 环境变量传入） | 同左 |

> ⚠️ 容器内网络（IP/网关）与 `/etc/resolv.conf` 由 **PVE 侧托管**：容器无
> `/etc/network/interfaces`、`/etc/netplan` 为空，systemd-networkd 由 PVE hook 喂配置。
> **改网络/DNS 要用 `pct set`，在容器内直接改文件重启后会被覆盖。**

---

## 二、PVE 侧准备

### 2.1 宿主机网络

只需要一个桥：`vmbr0`（接现有 LAN，能出公网）。**不再需要 vmbr2 测试内网。**
201 和 202 都接在 vmbr0，和你的 PC/手机/上游路由器处于同一个二层网段。

> 如果 LAN 不是 192.168.1.0/24，不用改任何脚本：把下面命令里的 IP 换成你网段的空闲地址即可，
> 201 的 LAN 地址/网段由 `default route + eth0 地址` 自动推导。

### 2.2 容器创建（已有则跳过）

```bash
# 201：单网卡，LAN=WAN 同一个 eth0；默认网关保持上游路由器
pct create 201 local:vztmpl/ubuntu-24.04-standard-amd64.tar.zst \
  --hostname router --unprivileged 1 --cores 1 --memory 512 \
  --net0 name=eth0,bridge=vmbr0,ip=192.168.1.212/24,gw=192.168.1.1

# 202：同一网段，网关和 DNS 都指向 201
pct create 202 local:vztmpl/ubuntu-24.04-standard-amd64.tar.zst \
  --hostname client --unprivileged 1 --cores 1 --memory 512 \
  --net0 name=eth0,bridge=vmbr0,ip=192.168.1.202/24,gw=192.168.1.212
```

> 已在跑的双网卡 201 可以直接删掉 eth1（实测不影响业务）：
> `pct set 201 --delete net1`。删完 201 只剩 eth0，dnsmasq 也只监听 eth0。

### 2.3 DNS 持久化（关键，容器重启后 resolv.conf 由此决定）

```bash
pct set 201 --nameserver 127.0.0.1
pct set 202 --nameserver 192.168.1.212
```

### 2.4 部署前快照（必做）

```bash
pct snapshot 201 pre-deploy-20261030 --description 'deploy route-gw before'
pct snapshot 202 pre-deploy-20261030 --description 'deploy route-gw before'
# 查看: pct listsnapshot 201
# 回滚: pct rollback 201 pre-deploy-20261030 && pct start 201
```

> 本环境另有装面板前的快照 `pre-web-20261031`（201/202 两台都有同名一份；面板只装在 201，
> 网关配置在 `pre-deploy-20261030` 里更干净）。回滚会丢掉回滚点之后的所有改动。

> 注意子命令是单数：`listsnapshot` / `delsnapshot` / `rollback`。
> 写错成 `pct snapshot 201 list` 会真的创建一个名叫 list 的快照（本次部署踩过）。

---

## 三、LXC 201 部署（网关）

把本目录整个放到 201 的 `/opt/` 下，然后执行安装脚本：

```bash
# 在 PVE 宿主机上
pct push 201 route-gw-deploy.tar.gz /tmp/route-gw-deploy.tar.gz
pct exec 201 -- tar --no-same-owner -xzf /tmp/route-gw-deploy.tar.gz -C /opt
pct exec 201 -- bash /opt/route-gw-deploy/install.sh
```

> `--no-same-owner` 必加：从 Windows 打的 tar 带 Windows uid，容器内 chown 会报错。

`install.sh` 做了 8 件事（详见脚本注释）：

1. **装包**：wireguard-tools、dnsmasq、curl、cron、iptables、iproute2。
   开装前等待 dpkg 锁最多 5 分钟——Ubuntu 模板首次开机可能有残留的交互式
   `apt-get install iptables-persistent` 卡死占锁（本次部署踩过：
   `kill` 残留进程后 `DEBIAN_FRONTEND=noninteractive dpkg --configure -a` 收尾）。
2. **投放配置**：wg0.conf → `/etc/wireguard/`（600），三个脚本 → `/usr/local/bin/`（755，
   安装时 `sed -i 's/\r$//'` 防 CRLF），dnsmasq/cron/sysctl/dnsmasq-service 覆盖配置。
3. **sysctl**：`ip_forward=1`、`send_redirects=0`、`accept_redirects=0`、`rp_filter=2`
   （持久化于 `/etc/sysctl.d/99-route-gw.conf`；per-interface 值由 `wg-route-up.sh` 再校准）。
4. **接管 DNS**：停用并禁用 systemd-resolved（让出 53 端口），`/etc/resolv.conf` 写死 127.0.0.1；
   `00-listen.conf` 按默认路由网卡生成，不写死接口/IP。
5. **拉起隧道**：`systemctl enable --now wg-quick@wg0`，PostUp 自动部署策略路由 + 动态 LAN NAT。
6. **首次拉数据源**：跑 `update-lists.sh`（github 走隧道下载，先有隧道后有列表）。
7. **自启**：dnsmasq、cron enable + start。
8. **打印状态快照**，见第五节验证标准。

### 3.1 WireGuard 配置（`/etc/wireguard/wg0.conf`）

```ini
[Interface]
PrivateKey = <本目录 files/etc/wireguard/wg0.conf> # 没有真实值 在AI读取到这里的时候一键部署需要提前询问或者让用户输入
Address = 10.14.0.2/16
MTU = 1420
FwMark = 0xca6c          # = 十进制 51820，WG 自身流量打标防死循环
Table = 51820            # wg-quick 把 AllowedIPs 的两条 /1 写入表 51820，不动主表默认路由
PostUp = /usr/local/bin/wg-route-up.sh
PostDown = /usr/local/bin/wg-route-down.sh

[Peer]
PublicKey = <你的对端公钥>
AllowedIPs = 0.0.0.0/1, 128.0.0.0/1
Endpoint = 203.0.113.9:51820
PersistentKeepalive = 25
```

> 与旧版差异：**没有 `DNS =` 行**。DNS 全归 dnsmasq 管，避免 wg-quick 改写
> `/etc/resolv.conf`（201 本机、202 客户端都依赖 dnsmasq 的按域名分流能力）。
>
> `[Peer]` 只是部署时的初值。装上管理面板后，这一节由面板按节点池改写
> （切节点=改写本文件 + `wg syncconf`）。本文写作时 203.0.113.9 的 WG 端口已不通
> （ICMP 仍通，见 3.6-4），面板当前落在同组其它节点上——以 `wg show wg0 dump` 为准。

### 3.2 策略路由原理

```
32764: from all lookup main suppress_prefixlength 0   # 查主表，忽略 0.0.0.0/0 默认路由
32765: not from all fwmark 0xca6c lookup 51820        # 未打标流量 → 表51820 → wg0
```

- 国内 IP：命中主表里 `wg-route-up.sh` 灌入的 ~7400 条 `/etc/china_ip_list.txt` 明细路由（最长前缀匹配），eth0 直连。
- 其余 IP：落到表 51820 的 `0.0.0.0/1 + 128.0.0.0/1`，走 wg0。
- **`AllowedIPs = 0.0.0.0/1, 128.0.0.0/1` 不是笔误**：两条 /1 合起来覆盖全部 IPv4，
  同时不会去碰主表默认路由；配合 `Table = 51820` 和规则 32765，正好实现"只接管非国内流量"。
  写成 `0.0.0.0/0` 也能覆盖全部 IPv4，但更依赖 `Table=51820` 始终生效；一旦 Table 丢失，
  `wg-quick` 会把默认路由写进主表，直接顶掉 `.1`，风险更大。排障时不要先改这里。
- WG 自身流量带 0xca6c 标记跳过 32765，经 anti-loop `/32` 直连对端，防隧道套隧道。
- **32764/32765 是分流总开关**：缺任意一条，`wg0` 即使握手成功也完全不参与转发，
  所有流量仍走主表 `.1`，表现为"国内正常、海外全挂/像断网"。面板 `health_loop` 每 3 秒自检并自动补回；
  `wg-route-up.sh` 也带重试和显式校验。
- **同网段旁路由的转发**：客户端 -> 201 的包目的地址仍是公网 IP，`ip_forward=1` 后按上面两条规则选路；
  从 eth0 直连的做 `-s <LAN_NET> ! -d <LAN_NET> -o eth0 MASQUERADE`（SNAT 成 201），
  从 wg0 出去的做 `-s <LAN_NET> ! -d <LAN_NET> -o wg0 MASQUERADE`（SNAT 成 10.14.0.2）。
  `LAN_NET` 每次启动按 `默认路由网卡 + 地址前缀` 现算，不写死。

### 3.3 DNS 分流（dnsmasq）

| 配置项 | 值 |
|--------|-----|
| 监听 | lo + 默认路由网卡（`bind-dynamic`；接口名由 `00-listen.conf` 跟随，不写死 IP） |
| 国内上游 | 223.5.5.5、114.114.114.114 |
| GFW 域名上游 | `/etc/default/route-gw` 的 `GW_GFW_DNS`（无标记流量 → 表51820 → 走 wg0 出） |
| gfwlist 生成规则 | `/etc/dnsmasq.d/99-gfw.conf`（cron 每日覆盖重写） |
| 手工补充域名 | `/etc/dnsmasq.d/98-custom-domain.conf`（cron 不动它） |
| 面板下发域名 | `/etc/dnsmasq.d/97-panel.conf`（管理面板「分流规则」生成，勿手改，见 WEB-DEPLOY.md） |

### 3.4 脚本一览（`/usr/local/bin/`）

| 脚本 | 触发 | 职责 |
|------|------|------|
| `wg-route-up.sh` | PostUp / 手动 / cron 联动 | 现算 LAN 网段、策略规则、anti-loop、灌国内路由、**动态 LAN NAT**、FORWARD、**TCPMSS 钳制**、sysctl、DNS 监听接口 |
| `wg-route-down.sh` | PostDown | 删国内路由、anti-loop、策略规则；摘除并删除 NAT/FORWARD/MSS 三条自定义链 |
| `update-lists.sh` | 每日 04:30 cron / 手动 | 拉 china_ip_list + gfwlist → 校验 → 原子替换 → 重启 dnsmasq → 重灌路由 + 校准 NAT |

### 3.5 v3.0 相对 CT107 v2.0 的关键修复（都实测踩过）

1. **anti-loop endpoint 解析**：旧版 PostUp/PostDown 用 `wg show wg0 endpoints` 取对端 IP，
   但 PostUp 时通常还没握手 → 拿到空串，anti-loop 路由**静默漏加**。现改为从 wg0.conf 静态解析。
2. **TCPMSS 黑洞修复（最重要）**：对端返回的 1460 字节 TCP 段带 DF 位，转发进 MTU 1420 的
   wg0 时无法分片 → 表现为**TCP 握手成功、小请求正常、大响应（TLS ServerHello/页面/下载）全部
   超时**，201 本机却正常（本机 socket 自动遵守 PMTU）。修复：
   `iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu`
   （已内置进 wg-route-up.sh 第 6 节）。旧文档环境大概率同样存在此问题，只是没测转发大流量。
3. **update-lists 刷新条件**：旧版 `grep -q 'priority 32764'` 匹配不上 `ip rule show` 的真实
   输出格式（`32764:\t...`），每日更新后路由不会重灌。改为 `grep -q '32764:'`。
4. **WAN 网关自动探测**：不再硬编码 192.168.1.1，从主表默认路由动态取。
5. **apt 锁等待** + `dpkg --configure -a` 兜底，模板首启残留不再阻断安装。
6. `update-lists.sh` 给出完整实现（旧文档正文省略），并明确：gfwlist 的 `@@` 例外规则**跳过**
   （例外域名仍可能走 WG，需要精确直连的域名请手工加进 98-custom-domain 并另行处理）。
7. **v3.1 同网段单臂修复**：
   - NAT 从写死 `192.168.99.0/24` 改为按默认路由网卡现算的 `LAN_NET`；
   - 不再依赖 eth1/vmbr2，201 只保留 eth0；
   - 必须 `send_redirects=0`，否则同网段客户端会被 ICMP redirect 引到上游网关；
   - `bind-dynamic` + 生成的 `00-listen.conf` 让 DNS 跟随接口地址变化；
   - nft 后端的 `iptables` 不允许一条规则里出现两个 `-s`，NAT 规则已改成单 `-s`；
   - anti-loop endpoint 解析修正（旧 `awk -F'[ =:]'` 取到的是端口而不是 IP）。

### 3.6 本机 wireguard-tools 的两个坑（v1.0.20210914，面板换节点依赖）

1. **`wg syncconf wg0 -` 不支持**：这个版本把 `-` 当成文件名去 `fopen`，报
   `fopen: No such file or directory` 且返回码 1 —— 换 peer 看起来"执行了"其实什么都没发生，
   `wg0.conf` 与运行中的隧道从此永久分叉。可用写法：

   ```bash
   wg-quick strip wg0 > /tmp/x.conf && wg syncconf wg0 /tmp/x.conf   # 明文落盘，不推荐
   wg-quick strip wg0 | wg syncconf wg0 /dev/stdin                    # 面板采用：私钥不落盘
   ```

   `syncconf` 与 `down+up` 的区别：不重建接口、不动策略路由、下挂设备不断网。
2. **改对端入口必须带 peer**：`wg set wg0 peer <_pubkey> endpoint <ip:port>`；
   写成 `wg set wg0 endpoint <ip:port>` 会报 `Invalid argument: endpoint`。
3. 手工把在线 peer 的入口指向黑洞，约 10 秒内会被 WireGuard 的**入口漫游**自动纠正回来
   （旧对端还在发认证包）。要模拟"真死了"得用 iptables 双向丢 UDP：
   `iptables -I INPUT 1 -s <对端IP> -p udp --sport 51820 -j DROP` + 对应 OUTPUT 规则，
   测完记得 `-D` 删掉。
4. **ICMP 通 ≠ 隧道能用**：矩阵页的 `alive`/延迟是 ICMP 探测结果。同一城市里存在
   ping 82~95ms 但 WG 端口永不握手的节点（本次 TW_Taiwan_59/.60/.77 即如此）。
   所以"能不能切"只能由真实握手决定，面板切换失败会回滚并把该节点标记故障。

### 3.7 Ubuntu 26.04 原生机的 wg-quick AppArmor

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

`install.sh` 检测到 `/etc/apparmor.d/wg-quick` 时会自动合并这段 local override。
本仓库的 `files/etc/apparmor.d/local/wg-quick` 就是该文件。迁移完整步骤见 **MIGRATE.md**。

> 路由灌入/删除已改成 `ip -batch`：J1900 上 PostUp 从 ~49 秒降到 ~2 秒，
> `systemctl restart wg-quick@wg0` 约 4 秒。

---

## 四、LXC 202 部署（客户端）

```bash
pct push 202 route-gw-deploy/setup-202.sh /opt/setup-202.sh
pct exec 202 -- bash /opt/setup-202.sh            # 自动取当前默认网关
# 或显式指定: pct exec 202 -- bash /opt/setup-202.sh 192.168.1.212
```

脚本做三件事：确认默认网关就是旁路由；停用 systemd-resolved 并把 `/etc/resolv.conf`
写成 `nameserver <旁路由IP>`；做 DNS/连通性自检。**网关本身由 PVE 侧 `pct set 202 --net0 ...,gw=...` 决定**，
脚本不会改路由表。重启持久化同时靠 2.3 节 `pct set 202 --nameserver`。

> 同网段的手机/PC/NAS 不需要跑这个脚本：在网络设置里把「默认网关」和「DNS」都填成 201 的 LAN 地址即可。
> 关键点：**两个都必须是 201**，只改网关不改 DNS 会让域名层分流失效。

---

## 五、部署后验证（标准结果）

```bash
# --- 201 上 ---
systemctl is-active wg-quick@wg0 dnsmasq cron     # active active active
wg show wg0 | grep handshake                       # latest handshake: xx 秒前（必须新鲜）
ip rule show | grep -E '32764|32765'              # 两条都在
ip route | wc -l                                   # ~7460+（含国内明细路由）
ip route show table 51820                          # 0.0.0.0/1 和 128.0.0.0/1 dev wg0
iptables -t mangle -S ROUTE_GW_MSS                 # 含 TCPMSS --clamp-mss-to-pmtu
iptables -t nat -S ROUTE_GW_NAT                    # 两条 MASQUERADE：-o eth0 与 -o wg0
wc -l /etc/china_ip_list.txt                       # > 5000 (本次 7456)
grep -c '^server=' /etc/dnsmasq.d/99-gfw.conf      # > 1000 (本次 4375)
ip -4 -br addr show eth0; ip route show default     # 确认 LAN 地址/上游网关（无 eth1）
cat /etc/dnsmasq.d/00-listen.conf                   # interface=lo + 默认路由网卡

# 分流矩阵（201 与同网段客户端上分别执行，结果应一致）
curl -s -m 15 http://myip.ipip.net      # 国内出口: 你的国内出口 IP  → 直连生效
curl -sk -m 15 https://1.1.1.1/cdn-cgi/trace | grep ^ip=   # WG 节点出口 IP → 隧道生效
curl -skL -m 25 -o /dev/null -w '%{http_code}\n' https://github.com      # 200 → 域名层生效
getent hosts baidu.com    # 国内 IP (124.x) → 国内 DNS 视角
getent hosts google.com   # 海外 IP (92.x)  → WG DNS 视角
```

重启持久化验证（PVE 侧）：`pct reboot 201 && sleep 50`（再起 202）后重跑上面矩阵。
本次部署两台均已实测重启自恢复通过。

> 装了管理面板之后，这节的矩阵仍然照用（面板不改网络行为）；面板自身的 12 项自检见
> **WEB-DEPLOY.md 第九节**。两边对不上时以这里的命令行为准——面板只是这些状态的读取器。

---

## 六、运维速查

```bash
# 隧道
systemctl restart wg-quick@wg0          # 重启会重跑 PostUp 全套
journalctl -u wg-quick@wg0 --no-pager | tail -30

# 钩子日志（脚本里 logger 打的）
journalctl -t wg-up -t wg-down -t route-update --no-pager | tail -40

# 数据源
/usr/local/bin/update-lists.sh          # 手动更新
tail -50 /var/log/update-lists.log      # cron 日志（04:30）

# DNS 查询日志（本容器 rsyslogd 抢不到 /dev/log，/var/log/syslog 是死的，只能看 journal）
journalctl -u dnsmasq.service -f
# log-queries 是启动期选项：改了要 systemctl restart dnsmasq，reload 不生效

# 排错一把梭（在 201 上）
wg show wg0; ip rule show; ip route | head; ip route show table 51820
iptables -t nat -S POSTROUTING; sysctl net.ipv4.ip_forward
```

## 七、故障处理

| 症状 | 排查 |
|------|------|
| 同网段主机完全不通 | `ping <201 LAN IP>` → `iptables -t nat -S ROUTE_GW_NAT`（两条 MASQUERADE）→ `ip_forward=1`；确认客户端网关和 DNS 都指向 201 |
| 能上国内、代理全不生效 | 先看 `ip rule show \| grep -E '32764\|32765'`：缺规则时 `wg0` 有握手也不会被使用；面板会在 3 秒内自动补回，也可手动 `/usr/local/bin/wg-route-up.sh`。再查客户端 DNS 是否指向 201、`ROUTE_GW_NAT` 是否缺 `-o wg0` |
| 切换节点后突然海外全挂 | 先确认 `ip rule` 两条规则是否还在；`AllowedIPs` 保持 `0.0.0.0/1,128.0.0.0/1`，不要改成 `0.0.0.0/0` 来"修"；规则丢失由面板自愈或手动重跑 `wg-route-up.sh` |
| 客户端能通但被"绕过" | `cat /proc/sys/net/ipv4/conf/<LAN_IF>/send_redirects` 必须为 0；否则客户端会被 ICMP redirect 引到上游网关 |
| 小网页能开、稍大的页面/下载卡死 | TCPMSS 规则丢失 → 见 3.5-2，跑 `wg-route-up.sh` 即恢复 |
| WG 无握手 | `journalctl -u wg-quick@wg0`；`bash /opt/route-gw-deploy/tools/peer-check.sh` 看当前对端是谁，再确认 201 能直连**那个** `IP:51820`（UDP）、对端密钥/端口配对。注意 `wg0.conf` 出厂写的 `.59` 端口已不通，别照它排错 |
| 数据源更新失败 | 多为隧道当时未恢复（下载走隧道）；隧道恢复后手动跑 `update-lists.sh` |
| 面板显示"当前节点"与实际隧道对不上 | 先 `bash /opt/route-gw-deploy/tools/peer-check.sh` 确认分叉 → 见 WEB-DEPLOY.md「一致性自愈」：`python3 /opt/gw-admin/gw_server.py --restore` 以隧道为准重写配置文件（不动在跑的 peer） |
| 节点 ping 得通却切不过去 | 该节点 WG 端口不通（3.6-4）；面板会 8s 握手超时后自动回滚，属正常保护，不是面板故障 |
| apt 卡 "Could not get lock" | 模板首启残留交互式 apt：`ps aux | grep apt` 找到后 kill，再 `dpkg --configure -a` |
| 回滚 | `pct rollback <vmid> pre-deploy-20261030 && pct start <vmid>`（会丢回滚点之后的数据） |

## 八、已知限制

- **仅 IPv4**：策略路由/明细路由都只覆盖 IPv4；若上游给了 IPv6，海外站点 AAAA 会原生直连出泄漏（本环境容器无 IPv6 地址，暂无影响）。
- **gfwlist 只管域名**：直接用 IP 访问、或客户端自带 DoH/硬编码 DNS 的应用不受 DNS 层管辖（仍受 IP 层国内列表约束）。
- **`@@` 例外规则跳过**：gfwlist 里标记直连的域名仍走 WG DNS 解析，但解析出的若为国内 IP 会被 IP 层拉回直连，实际影响小。
- `198.51.100.53` 是占位用的境外 DNS（见开头"部署前必须替换的占位符"），部署时用
  `GW_GFW_DNS=<真实地址> bash install.sh` 写进 `/etc/default/route-gw`；不配置就会把 gfw 域名
  指到一个不可用地址。
- 单臂旁路由依赖客户端把网关和 DNS 都改到 201；任何硬编码 DNS（DoH/DoT/应用内置）或 IPv6 直连都不受本方案管辖。
- **只服务同一二层 LAN**：不同网段的主机不能直接把本机 LAN IP 写成默认网关（下一跳不可达），
  需要把网关机接到该网段，或建 GRE/VXLAN 隧道；详见 MIGRATE.md 第 7 节。
- `/var/log/update-lists.log` 未配 logrotate，长期跑注意（可加 `/etc/logrotate.d/route-lists`）。

## 九、目录清单

```
route-gw-deploy/
├── README.md                     ← 总入口：目录导航、部署顺序、安全须知
├── DEPLOY.md                     ← 网关部署（本文档）
├── WEB-DEPLOY.md                 ← 管理面板部署与运维（在 201 上，紧接本文之后做）
├── MIGRATE.md                    ← 迁到原生 Ubuntu 主机（含 AppArmor/跨网段说明）
├── TEST-REPORT.md                ← 迁移后的客户端/Registry/大文件/强制重启报告
├── install.sh                    ← 201 一键安装网关
├── install-web.sh                ← 201 一键安装管理面板
├── setup-202.sh                  ← 202 客户端设置
├── files/
│   ├── etc/wireguard/wg0.conf            ⚠示例值，真实私钥自填，权限 600 投放
│   ├── etc/dnsmasq.conf
│   ├── etc/dnsmasq.d/00-listen.conf      （接口名由 install.sh/wg-route-up 生成）
│   ├── etc/dnsmasq.d/98-custom-domain.conf
│   ├── etc/cron.d/route-lists
│   ├── etc/sysctl.d/99-route-gw.conf
│   ├── etc/systemd/system/dnsmasq.service.d/override.conf
│   ├── etc/apparmor.d/local/wg-quick       ← Ubuntu 26.04+ PostUp 放行
│   └── usr/local/bin/{wg-route-up.sh,wg-route-down.sh,update-lists.sh}
├── tools/                        ← 辅助脚本（用法见 README.md 第二节）
│   ├── ssh_run.py                （paramiko 版，密码用 PVE_PW 环境变量传入）
│   ├── rexec.py                  （run/put/get，base64 送脚本进容器，免引号转义）
│   ├── upload.py                 （base64-over-ssh 传文件，绕开 sftp 被禁）
│   ├── portforward.py            （本机调试用端口转发；Windows 直连不到 192.168.1.0/24）
│   ├── peer-check.sh             （核对 wg0.conf 的对端与隧道真实对端是否分叉，在 201 上跑）
│   └── netcheck-202.sh           （客户端全面体检：IPv6泄漏/DNS双视角/ICMP/耗时/出口/
│                                  大下载/keepalive/稳定性/UDP53，在 202 上直接 bash 跑）
└── web/                          ← 管理面板（详见 WEB-DEPLOY.md）
    ├── app/                      Vue3 前端源码 + CONTRACT.md/ITERATION.md
    ├── server/gw_server.py       单文件 Python 标准库后端（201 上跑，无第三方依赖）
    ├── dist/                     已构建好的静态产物（没有 Node 环境也能直接部署）
    └── gw-admin.service          systemd 单元
```

在线重新打包：`tar czf route-gw-deploy.tar.gz route-gw-deploy`（Windows Git Bash 打包记得
解包时 `--no-same-owner`）。
