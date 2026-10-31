# CT 201 / CT 202 分流网关部署文档

> 日期: 2026-10-30 | 版本: v3.0（CT107/108 v2.0 方案的迁移重建版）
> 环境: PVE 9.1.1（宿主机 <PVE_HOST>），LXC 201/202，Ubuntu 24.04，非特权容器
> 本目录即完整部署包，可在新环境按本文一步步重建。
> 管理面板（Web）见同目录 **WEB-DEPLOY.md**；先看 **README.md** 了解本目录怎么组织。
> ⚠️ 本包内的 `wg0.conf` 是**示例值**（私钥留空、对端用占位符）。真实私钥只存在于你自己那台机器上，
> 永远不要写回本仓库、不要提交、不要贴进聊天工具。

---

## 一、架构概览

```
Internet
   │
   ├── 国内流量 ──→ eth0 (<GW_IP>/24, vmbr0, 网关 192.168.1.1)
   │                    │
   │              [策略路由: 查主表, 忽略默认路由]
   │              [主表灌入 ~7400 条国内明细路由]
   │
   └── 海外流量 ──→ wg0 (10.14.0.2/16, WireGuard 隧道)
                        │
                  203.0.113.9:51820 (远端节点；.59 只是 wg0.conf 的出厂初值，
                                       实跑节点由面板切换/自愈决定，见 §3.1 与 WEB-DEPLOY.md)
                        │
                  海外 Internet
```

- **LXC 201 (router)**：分流网关 + DNS。国内 IP 走 eth0 直连，其余走 wg0；dnsmasq 按 gfwlist 域名把海外域名解析到 WG 出口视角。
- **LXC 202 (client)**：单网卡接 vmbr2 测试内网（192.168.99.0/24），网关/DNS 都指向 201，所有流量跟随 201 分流。
- 分流三要素：**策略路由规则 + 国内 IP 明细路由（IP 层）+ gfwlist 域名 DNS 劫持（域名层）**，缺一不可。

### 设备清单

| 项目 | LXC 201 router | LXC 202 client |
|------|----------------|----------------|
| VMID | 201 | 202 |
| 用途 | 分流网关 + DNS | 测试节点 |
| eth0 | <GW_IP>/24（vmbr0，WAN 出口） | 192.168.99.2/24（vmbr2 内网） |
| eth1 | 192.168.99.1/24（vmbr2，内网网关） | — |
| wg0 | 10.14.0.2/16 | — |
| 默认网关 | 192.168.1.1（PVE 侧配置） | 192.168.99.1 |
| DNS | 127.0.0.1（本机 dnsmasq） | 192.168.99.1（201 dnsmasq） |
| 规格 | 1C / 512MB | 1C / 512MB |
| 密码 | root 密码见密码管理器（部署时用 `PVE_PW` 环境变量传入） | 同左 |

> ⚠️ 容器内网络（IP/网关）与 `/etc/resolv.conf` 由 **PVE 侧托管**：容器无
> `/etc/network/interfaces`、`/etc/netplan` 为空，systemd-networkd 由 PVE hook 喂配置。
> **改网络/DNS 要用 `pct set`，在容器内直接改文件重启后会被覆盖。**

---

## 二、PVE 侧准备

### 2.1 宿主机网络

需要两个桥：`vmbr0`（WAN，桥接到能出公网的物理网段）和 `vmbr2`（测试内网，可纯虚拟）。
若 vmbr2 不存在，在 `/etc/network/interfaces` 添加：

```
auto vmbr2
iface vmbr2 inet static
    address 192.168.99.1/24
    bridge-ports none
    bridge-stp off
    bridge-fd 0
```

（本例 PVE 主机上 vmbr2 已存在；201/202 的 IP 不依赖宿主机 vmbr2 地址，仅容器互通用。）

### 2.2 容器创建（已有则跳过）

```bash
pct create 201 local:vztmpl/ubuntu-24.04-standard-amd64.tar.zst \
  --hostname router --unprivileged 1 --cores 1 --memory 512 \
  --net0 name=eth0,bridge=vmbr0,ip=<GW_IP>/24,gw=192.168.1.1 \
  --net1 name=eth1,bridge=vmbr2,ip=192.168.99.1/24
pct create 202 local:vztmpl/ubuntu-24.04-standard-amd64.tar.zst \
  --hostname client --unprivileged 1 --cores 1 --memory 512 \
  --net0 name=eth0,bridge=vmbr2,ip=192.168.99.2/24,gw=192.168.99.1
```

### 2.3 DNS 持久化（关键，容器重启后 resolv.conf 由此决定）

```bash
pct set 201 --nameserver 127.0.0.1
pct set 202 --nameserver 192.168.99.1
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
3. **sysctl**：`net.ipv4.ip_forward=1`（持久化于 `/etc/sysctl.d/99-route-gw.conf`）。
4. **接管 DNS**：停用并禁用 systemd-resolved（让出 53 端口），`/etc/resolv.conf` 写死 127.0.0.1。
5. **拉起隧道**：`systemctl enable --now wg-quick@wg0`，PostUp 自动部署策略路由。
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
- WG 自身流量带 0xca6c 标记跳过 32765，经 anti-loop `/32` 直连对端，防隧道套隧道。

### 3.3 DNS 分流（dnsmasq）

| 配置项 | 值 |
|--------|-----|
| 监听 | lo / eth0 / eth1（`bind-interfaces`，需已停 systemd-resolved） |
| 国内上游 | 223.5.5.5、114.114.114.114 |
| GFW 域名上游 | 162.252.172.57（无标记流量 → 表51820 → 走 wg0 出） |
| gfwlist 生成规则 | `/etc/dnsmasq.d/99-gfw.conf`（cron 每日覆盖重写） |
| 手工补充域名 | `/etc/dnsmasq.d/98-custom-domain.conf`（cron 不动它） |
| 面板下发域名 | `/etc/dnsmasq.d/97-panel.conf`（管理面板「分流规则」生成，勿手改，见 WEB-DEPLOY.md） |

### 3.4 脚本一览（`/usr/local/bin/`）

| 脚本 | 触发 | 职责 |
|------|------|------|
| `wg-route-up.sh` | PostUp / 手动 / cron 联动 | 策略规则、anti-loop、灌国内路由、NAT、FORWARD、**TCPMSS 钳制**、ip_forward |
| `wg-route-down.sh` | PostDown | 删国内路由、anti-loop、两条规则（NAT/FORWARD 保留，幂等无害） |
| `update-lists.sh` | 每日 04:30 cron / 手动 | 拉 china_ip_list + gfwlist → 校验 → 原子替换 → 重启 dnsmasq → 重灌路由 |

### 3.5 v3.0 相对 CT107 v2.0 的关键修复（都实测踩过）

1. **anti-loop endpoint 解析**：旧版 PostUp/PostDown 用 `wg show wg0 endpoints` 取对端 IP，
   但 PostUp 时通常还没握手 → 拿到空串，anti-loop 路由**静默漏加**。现改为从 wg0.conf 静态解析。
2. **TCPMSS 黑洞修复（最重要）**：对端返回的 1460 字节 TCP 段带 DF 位，转发进 MTU 1420 的
   wg0 时无法分片 → 表现为**TCP 握手成功、小请求正常、大响应（TLS ServerHello/页面/下载）全部
   超时**，201 本机却正常（本机 socket 自动遵守 PMTU）。修复：
   `iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu`
   （已内置进 wg-route-up.sh 第 7b 节）。旧文档环境大概率同样存在此问题，只是没测转发大流量。
3. **update-lists 刷新条件**：旧版 `grep -q 'priority 32764'` 匹配不上 `ip rule show` 的真实
   输出格式（`32764:\t...`），每日更新后路由不会重灌。改为 `grep -q '32764:'`。
4. **WAN 网关自动探测**：不再硬编码 192.168.1.1，从主表默认路由动态取。
5. **apt 锁等待** + `dpkg --configure -a` 兜底，模板首启残留不再阻断安装。
6. `update-lists.sh` 给出完整实现（旧文档正文省略），并明确：gfwlist 的 `@@` 例外规则**跳过**
   （例外域名仍可能走 WG，需要精确直连的域名请手工加进 98-custom-domain 并另行处理）。

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

---

## 四、LXC 202 部署（客户端）

```bash
pct push 202 route-gw-deploy/setup-202.sh /opt/setup-202.sh
pct exec 202 -- bash /opt/setup-202.sh
```

只有两件事：停用 systemd-resolved；`/etc/resolv.conf` 写 `nameserver 192.168.99.1`
（重启持久化靠 2.3 节 `pct set 202 --nameserver`）。
网关 192.168.99.1 在 PVE 侧 net0 已配好，无需动。

> ⚠️ 客户端 DNS 必须指向 201，否则域名层分流完全失效（旧文档缺失此节）。

---

## 五、部署后验证（标准结果）

```bash
# --- 201 上 ---
systemctl is-active wg-quick@wg0 dnsmasq cron     # active active active
wg show wg0 | grep handshake                       # latest handshake: xx 秒前（必须新鲜）
ip rule show | grep -E '32764|32765'              # 两条都在
ip route | wc -l                                   # ~7460+（含国内明细路由）
ip route show table 51820                          # 0.0.0.0/1 和 128.0.0.0/1 dev wg0
iptables -t mangle -S FORWARD                      # 含 TCPMSS --clamp-mss-to-pmtu
wc -l /etc/china_ip_list.txt                       # > 5000 (本次 7456)
grep -c '^server=' /etc/dnsmasq.d/99-gfw.conf      # > 1000 (本次 4372)

# 分流矩阵（201 与 202 上分别执行，结果应完全一致）
curl -s -m 15 http://myip.ipip.net      # 国内出口: <你的国内出口IP> (联通)  → 直连生效
curl -sk -m 15 https://1.1.1.1/cdn-cgi/trace | grep ^ip=   # 203.0.113.x = 当前 WG 节点出口 → 隧道生效
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
| 202 完全不通 | `ping 192.168.99.1`（网关）→ `iptables -t nat -S`（MASQUERADE）→ `ip_forward=1` |
| 202 能上国内、代理全不生效 | 策略规则丢失 → `systemctl restart wg-quick@wg0`；**或 202 DNS 没指向 192.168.99.1** |
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
- 162.252.172.57 / 149.154.159.92 是 WG 服务方提供的境外 DNS，失效需换；149.154.159.92 当前仅作备胎未实际使用（dnsmasq 只用 162.252.172.57）。
- `/var/log/update-lists.log` 未配 logrotate，长期跑注意（可加 `/etc/logrotate.d/route-lists`）。

## 九、目录清单

```
route-gw-deploy/
├── README.md                     ← 总入口：目录导航、部署顺序、安全须知
├── DEPLOY.md                     ← 网关部署（本文档）
├── WEB-DEPLOY.md                 ← 管理面板部署与运维（在 201 上，紧接本文之后做）
├── install.sh                    ← 201 一键安装网关
├── install-web.sh                ← 201 一键安装管理面板
├── setup-202.sh                  ← 202 客户端设置
├── files/
│   ├── etc/wireguard/wg0.conf            ⚠示例值，真实私钥自填，权限 600 投放
│   ├── etc/dnsmasq.conf
│   ├── etc/dnsmasq.d/98-custom-domain.conf
│   ├── etc/cron.d/route-lists
│   ├── etc/sysctl.d/99-route-gw.conf
│   ├── etc/systemd/system/dnsmasq.service.d/override.conf
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
