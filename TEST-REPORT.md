# 迁移与压力测试报告（CT201 → J1900 192.168.0.125）

> 日期：2026-11-01
> 目标：把 CT201 的 route-gw 全套配置迁到原生 Ubuntu 主机 J1900（192.168.0.125），
> 验证同网段旁路由、Docker Registry 拉取、大文件下载，以及断电/强制重启后的自恢复。

## 一、拓扑

| 设备 | 地址 | 说明 |
|---|---|---|
| CT201（旧网关） | `192.168.1.212/24` | 隧道/面板已停用并 disable，dnsmasq 保留 |
| CT202（旧客户端） | `192.168.1.202/24` | 仍在 1 网段；没有改成 J1900 的网关（原因见第三节） |
| J1900（新网关） | `192.168.0.125/24`，网关 `192.168.0.1` | Ubuntu 26.04，单网卡 `enp3s0`，route-gw 新家 |
| 测试客户端 | `192.168.0.250/24` | J1900 上的 netns，模拟同网段 0.x 主机 |

J1900 的 LAN 是 `192.168.0.0/24`；CT202 的 LAN 是 `192.168.1.0/24`。两者不在同一二层，
所以 **CT202 不能直接把 `192.168.0.125` 写成默认网关**：下一跳不在同一网段，内核无法 ARP，
会直接断网。要那样做只能把 J1900 网线接到 1 网段，或在 PVE 与 J1900 之间建 GRE/VXLAN 隧道。

因此本次按“在 0 网段找客户端”的方式测试：在 J1900 上创建 netns + veth，源地址 `192.168.0.250`，
默认网关/DNS 指向 `192.168.0.125`，与真实 0.x 主机走同一条转发/NAT 路径。

## 二、迁移内容

- `/etc/wireguard/wg0.conf`（真实私钥，600）
- `/etc/china_ip_list.txt`（7456 条）
- `/etc/dnsmasq.conf`、`/etc/dnsmasq.d/`（00/97/98/99）
- `/etc/default/route-gw`（真实境外 DNS）
- `/etc/cron.d/route-lists`
- `/etc/sysctl.d/99-route-gw.conf`
- `/etc/systemd/system/gw-admin.service` + `site.conf`
- `/etc/systemd/system/dnsmasq.service.d/override.conf`
- `/usr/local/bin/{wg-route-up,wg-route-down,update-lists}.sh`
- `/opt/gw-admin/`（后端 + dist + data：节点池/规则/订阅/事件/账号）

## 三、迁移中修掉的问题

1. **Ubuntu 26.04 wg-quick AppArmor**
   默认拒绝 PostUp/PostDown 执行 `/usr/local/bin/*.sh`，报 `Permission denied`。
   已加 `/etc/apparmor.d/local/wg-quick`，只放行两个钩子（`rux`），不动 wg-quick 其它策略。
2. **7400+ 条路由逐条 `ip route` 太慢**
   J1900 上原来 PostUp 约 49 秒；改成 `ip -batch` 后约 **2 秒**。
   `wg-route-down.sh` 同样批量化，`systemctl restart wg-quick@wg0` 约 **4 秒**。
3. **面板出口 IP 在 IPv6 主机上可能判断错**
   面板 `check_exit_ip` 改为优先 `curl -4`，正确显示隧道出口 `89.117.42.84`。
4. **Go 工具（skopeo 等）默认优先 IPv6**
   J1900 有全局 IPv6；在 `/etc/gai.conf` 增加 `precedence ::ffff:0:0/96 100`，
   并在测试时用 `GODEBUG=netdns=cgo`，否则 registry 访问会先走 IPv6 直连并被 reset。

## 四、测试结果

### 1. 基础服务（强制重启后）

```text
wg-quick@wg0  active
dnsmasq       active
gw-admin      active
cron          active
systemd-resolved inactive/disabled
wg handshake  56s 内新鲜
ip route      7463 条
```

启动耗时约 **42 秒**（BIOS 17s + 内核/initrd + 用户态 13.4s）。

### 2. 本机分流

```text
curl -4 https://api.ipify.org       → 89.117.42.84（WG 出口）
curl -4 https://www.baidu.com       → 200
dig @127.0.0.1 google.com           → 92.249.39.190（隧道 DNS）
dig @127.0.0.1 baidu.com            → 国内 IP
http://127.0.0.1:8080/              → 200
```

从 Windows 真实网络侧验证：

```text
Resolve-DnsName google.com -Server 192.168.0.125 → 92.249.39.190
Resolve-DnsName baidu.com  -Server 192.168.0.125 → 国内 IP
http://192.168.0.125:8080/                       → 200
```

### 3. 0.x 客户端（netns 192.168.0.250）

| 测试 | 结果 |
|---|---|
| 百度 HTTPS | 200 |
| `api.ipify.org` | `89.117.42.84` |
| Google HTTPS | 200 |
| 5MB 下载 | 200 |
| 50MB 下载 ×2（强制重启后） | 200 / 200，5.7 MB/s、12.8 MB/s |
| 面板 | 200 |

### 4. Docker Registry 镜像拉取（0.x 客户端，真实 registry 协议）

用 `skopeo`（containers/image，实际拉 manifest + config + layers）：

| 镜像 | 结果 | 大小 |
|---|---|---|
| `docker.io/library/alpine:3.20` | 成功 | 3.5 MB |
| `docker.io/library/ubuntu:24.04` | 成功 | 29 MB |

说明：本机没有安装 Docker daemon，使用 skopeo 是为了不把 Docker 的 iptables 规则带到网关；
拉取路径与 `docker pull` 的 registry/layer 下载路径一致。

### 5. J1900 本机大文件

| URL | 结果 |
|---|---|
| `https://ash-speed.hetzner.com/100MB.bin` | 200，100 MB，约 0.95 MB/s |
| `https://proof.ovh.net/files/100Mb.dat` | 100 MB 已传完，但 120s 超时；约 0.84 MB/s |
| `https://speed.cloudflare.com/__down?bytes=50000000` | 200，50 MB，约 1.16 MB/s |

速度受当前 WG 节点/线路影响，测试期间 0.x 客户端 50MB 曾达到 10–12 MB/s。

### 6. 断电/强制重启恢复

用 `systemctl reboot --force --force` 模拟非正常断电（跳过正常关机流程），重启后：

- SSH 恢复，boot id 变化，启动 42 秒
- `wg-quick@wg0` / `dnsmasq` / `gw-admin` / `cron` 全部自动 active
- 路由 7463 条、NAT/策略规则自动重建
- WG 握手 6 秒内恢复
- 面板 200，DNS/分流正常
- 0.x 客户端 50MB 下载、registry 拉取再次通过

## 五、结论

- J1900 已完整接管 CT201 的网关 + DNS + 面板 + 节点/规则数据。
- 同网段 0.x 客户端把网关和 DNS 指向 `192.168.0.125` 即可分流。
- Docker Registry 拉取（alpine/ubuntu）与大文件下载（50/100MB）通过。
- 强制重启后全部自恢复，满足“断电后恢复”的预期。
- **CT202 不能跨网段直接使用 J1900 作为网关**；它仍在 1 网段。若要让它也走 J1900，
  需要把 J1900 接到 1 网段，或在 PVE/J1900 之间建 GRE/VXLAN。当前没有做这个改动，
  以免破坏 0 网段和现有管理网络。

## 六、遗留注意事项

1. J1900 的 `.125` 目前是 DHCP 获取；建议在 `192.168.0.1` 上做 DHCP 静态绑定。
2. 本方案只分流 IPv4；J1900 和客户端若有 IPv6 默认路由，IPv6 流量仍直连上游。
3. CT201 的 `wg-quick@wg0` / `gw-admin` 已 disable；不要和 J1900 同时启动（同一个 WG peer）。
4. 面板账号 `admin`，地址 `http://192.168.0.125:8080`；迁移后为交付方便重置过密码，
   登录后请在「系统设置 → 账号安全」改成自己的密码。忘记时可用
   `sudo python3 /opt/gw-admin/gw_server.py --set-password admin '新密码'` 重置并
   `sudo systemctl restart gw-admin`。

## 七、2026-11-01 策略规则丢失事件

现象：切换节点后 `wg0` 仍有握手，但海外站点全挂，像是断网。检查发现：

```text
ip rule show
0:      from all lookup local
32766:  from all lookup main
32767:  from all lookup default
```

**32764/32765 两条分流规则缺失**。此时 `wg0` 虽然握手成功，但没有任何流量被规则 32765
送去表 51820，所有流量仍走主表 `.1`，所以国内正常、海外被墙。

- **不是 `AllowedIPs` 的问题**：`0.0.0.0/1 + 128.0.0.0/1` 覆盖全部 IPv4，
  配合 `Table=51820` 是正确写法；改成 `0.0.0.0/0` 不会解决，反而更依赖 Table 不丢失。
- 已修复：
  - `wg-route-up.sh` 给 32764/32765 加 5 次重试，并在末尾显式校验/记日志；
  - 面板 `health_loop` 每 3 秒检查，发现规则缺失立即补回并写自愈事件；
  - 节点切换/回滚成功后也调用一次 `ensure_policy_rules()`。
- 已实测：手动删掉两条规则，面板 6 秒内补回；停面板后重跑 `wg-route-up.sh` 也能补回；
  切换失败回滚后规则仍在。
