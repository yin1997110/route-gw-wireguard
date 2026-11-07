# route-gw — 单机旁路由（WireGuard 策略路由分流）+ 管理面板

一台**单网卡 Linux 主机**同时当网关和 DNS：国内 IP 段直连、其余走 WireGuard 隧道；DNS 按域名分流；
主表默认路由全程不动。**同网段任意主机只要把「默认网关 + DNS」都指向本机就自动跟随分流**，
不需要第二块网卡、不需要改客户端路由表。

自带零依赖管理面板（单文件 Python 标准库后端 + Vue3 前端），负责节点切换、数据源状态展示和配置/隧道一致性自愈。
节点在线与延迟由数据源扫描提供，本机不再逐节点探测。

> 实测环境：**J1900 小主机 · Ubuntu 26.04.1 LTS · 单网卡 `enp3s0`**
> LAN `192.168.0.0/24`（网关机 `192.168.0.125`，上游路由器 `192.168.0.1`）· WireGuard 接口 `wg0`
> 文档里的地址统一用 `<GW_IP>` / `<UPSTREAM_GW>` / `203.0.113.x`（RFC 5737 文档保留段）占位。

---

## 一、按什么顺序读

| 你要做什么 | 读哪个文件 |
|---|---|
| 搭分流网关（网络层） | **DEPLOY.md** |
| 网关之上再装管理面板 | DEPLOY.md 做完 → **WEB-DEPLOY.md** |
| 自建/修改节点数据源，或对接 `data.js` 格式 | **MATRIX-FORMAT.md** |
| 让 LAN 客户端访问 ZeroTier/Tailscale 网络 | **OVERLAY.md** |
| 只想快速上手 | 本文「三、快速开始」 |
| 改前端代码 / 加功能 | **web/app/CONTRACT.md** + **web/app/ITERATION.md** |
| 排障 | DEPLOY.md §七 · WEB-DEPLOY.md §十 |

**部署顺序是固定的：网关 → 面板。** 面板读网关的运行状态（`wg0`、策略路由、dnsmasq、数据源），
网关没起来时面板只能显示空壳。

---

## 二、目录导航

```
route-gw-wireguard/
├── README.md                  ← 本文：总入口
├── DEPLOY.md                  ← 网关部署（架构原理 + 步骤 + 验证标准 + 故障处理）
├── WEB-DEPLOY.md              ← 面板部署（部署/登录/与网关融合点/换节点语义/运维）
├── MATRIX-FORMAT.md           ← data.js 节点源格式约定
├── OVERLAY.md                 ← LAN 客户端访问 ZeroTier/Tailscale 的 NAT 方案
├── install.sh                 ← 在网关机上以 root 执行：一键装网关（8 步，幂等）
├── install-zerotier.sh        ← 安装 ZeroTier、加入网络（ID 由参数传入）并启用 overlay NAT
├── install-web.sh             ← 在网关机上以 root 执行：一键装/升面板（幂等，不覆盖 data/）
├── files/                     ← 要落到系统里的配置文件原文（wg0.conf 是示例值，私钥需自填）
│   ├── etc/wireguard/wg0.conf
│   ├── etc/dnsmasq.conf
│   ├── etc/dnsmasq.d/00-listen.conf          ← DNS 监听接口（跟随默认路由网卡）
│   ├── etc/dnsmasq.d/98-custom-domain.conf
│   ├── etc/cron.d/route-lists
│   ├── etc/sysctl.d/99-route-gw.conf
│   ├── etc/apparmor.d/local/wg-quick         ← Ubuntu 26.04+ 放行 PostUp/PostDown 钩子
│   ├── etc/systemd/system/dnsmasq.service.d/override.conf
│   ├── etc/systemd/system/route-gw-overlay.service
│   ├── etc/systemd/system/dnsmasq-healthcheck.{service,timer}   ← DNS 自愈定时器
│   └── usr/local/bin/{wg-route-up.sh, wg-route-down.sh, update-lists.sh,
│                      overlay-route-up.sh, overlay-route-down.sh, dnsmasq-healthcheck.sh}
├── tools/
│   └── peer-check.sh          ← 核对 wg0.conf 的对端与隧道真实对端是否分叉（退出码 0=一致 1=分叉）
└── web/                       ← 管理面板
    ├── app/                   Vue3 + Element Plus 前端源码（含 CONTRACT.md / ITERATION.md / mock-server.js）
    │   └── dist/              已构建好的静态产物 —— 没有 Node 环境也能直接部署
    ├── server/gw_server.py    单文件后端，纯 Python 标准库，跑在网关机上
    └── gw-admin.service       systemd 单元
```

落位（部署后）：

| 包内位置 | 系统位置 | 说明 |
|---|---|---|
| `files/etc/**` | `/etc/**` | 网关配置，权限由 install.sh 设置（wg0.conf 600） |
| `files/usr/local/bin/*.sh` | `/usr/local/bin/` | 755，install 时 `sed 's/\r$//'` 去 CRLF |
| `web/server/gw_server.py` | `/opt/gw-admin/gw_server.py` | 后端本体 |
| `web/app/dist/` | `/opt/gw-admin/dist/` | 前端静态产物（vite 构建输出，随包分发） |
| `web/gw-admin.service` | `/etc/systemd/system/gw-admin.service` | `systemctl enable --now gw-admin` |
| — | `/opt/gw-admin/data/*.json(l)` | **运行数据**（节点池/规则/订阅/事件/会话/状态），升级不动它 |

---

## 三、快速开始（在网关机上按序执行）

前提：网关机已装好系统、配好 LAN 地址与上游网关（单网卡、LAN 与 WAN 同一个口），本目录已放到 `/opt/route-gw-deploy`。

```bash
# 1) 装网关（装包、起隧道、灌 ~7400 条国内路由、拉数据源，约 2~4 分钟）
#    GW_GFW_DNS 是隧道内境外 DNS，写到 /etc/default/route-gw，不落仓库
sudo GW_GFW_DNS='<隧道内DNS>' bash /opt/route-gw-deploy/install.sh

# 2) 装管理面板（不给密码就随机生成一个并打印在终端）
sudo ADMIN_PASSWORD='换成你的密码' GW_GFW_DNS='<隧道内DNS>' \
  bash /opt/route-gw-deploy/install-web.sh
```

装完用 DEPLOY.md §五（网关矩阵）和 WEB-DEPLOY.md §九（面板自检）逐条验收。
浏览器开 `http://<GW_IP>:8080`，用 `admin` + 上面的密码登录。

**同网段任意主机接入**：在网络设置里把「默认网关」和「DNS」都填成 `<GW_IP>`。
两个都必须指向本机；只改网关会让域名分流失效。

---

## 四、🔐 机密处理须知（先看完再动手）

本包**不含任何真实机密**，可以放心公开：`wg0.conf` 里的私钥留空、对端公钥与入口都是占位符。

1. WG 密钥自己生成：`wg genkey` 出私钥、`wg pubkey` 出公钥；`PublicKey`/`Endpoint` 从你的服务商处拿。
   落到机器里权限 600，且不要把改过的 `wg0.conf` 提交回来。
   **`install.sh` 升级时不会覆盖已有的 `/etc/wireguard/wg0.conf`**，避免把在用的私钥冲成占位值；
   确需重置示例配置时才用 `FORCE_WG_CONF=1 bash install.sh`。
2. 隧道内 DNS 上游走 `/etc/default/route-gw` 的 `GW_GFW_DNS`，不要写进仓库。
3. 面板管理员密码：`install-web.sh` 打印出来的那个 / 你传入的 `ADMIN_PASSWORD`。
   库里存的是 PBKDF2-SHA256(120000 次) 哈希（`/opt/gw-admin/data/credentials.json`），**不落明文**。
   想清楚一件事：**能登面板 ≈ 能 root 这台网关**（可改策略路由、可重启 wg-quick/dnsmasq）。

**泄露了怎么办**：换 WG 密钥（服务商侧重签 → 改 `wg0.conf` → `systemctl restart wg-quick@wg0`）；
改面板密码（页面「系统设置 → 账号安全」，或忘了密码就在网关机上
`python3 /opt/gw-admin/gw_server.py --set-password admin '新密码'`）。

面板的「备份导出」JSON 含手动节点/规则/订阅/账号哈希，但**不含 WG 私钥**；
`/etc/wireguard/wg0.conf` 只读进、不写出，接口响应里永远不会出现 `PrivateKey`。
调试时也别顺手 `wg showconf wg0`——它会把私钥原样打到终端上。

---

## 五、这套东西到底是什么

- **分流网关（本机，单臂旁路由）**：三层配合 —— 策略路由规则 + 国内 IP 明细路由（IP 层）+ gfwlist 域名 DNS 劫持（域名层）。
  国内 IP 走 LAN 网卡直连，其余走 `wg0`；同网段客户端的网关/DNS 都指向本机，所以自动跟随分流。
  客户端流量从 LAN 网卡进来，转发后仍从 LAN 网卡（直连）或 `wg0`（隧道）出去，NAT 按运行时算出的 LAN 网段做。
- **管理面板（也在这台机）**：Vue3 前端（预构建静态产物）+ 单文件 Python 标准库后端 + systemd 常驻。
  左侧菜单 11 页：**仪表盘 / 节点管理 / 分流规则 / 自动切换与自愈 / DNS 管理 / 客户端设备 / 切换历史 /
  日志查看 / 数据源 / 系统设置 / 事件日志**。前 6 页是可操作的日常刚需，后 5 页是观测面。
  换节点是「写 `wg0.conf` → `wg syncconf` → 等握手 → 实测 → 不达标就回滚」七步，失败不会把隧道留在坏状态。
- **约束决定了形态**：J1900 只有 4 核 / 8GB、没有 node/npm/pip/nginx/jq/git 也能跑。
  所以后端不用任何第三方库、前端预构建、`dist` 直接随包分发。

---

## 六、已踩过的坑（文档里都有对应章节，这里只给索引）

| 坑 | 表现 | 见 |
|---|---|---|
| `tar` 带 Windows uid | 解包 chown 报错 | 需 `tar --no-same-owner` |
| Ubuntu 模板/首启残留交互式 apt | `Could not get lock` | DEPLOY.md §三 |
| PostUp 时 `wg show endpoints` 为空 | anti-loop 路由静默漏加 | DEPLOY.md §3.5-1 |
| 对端 DF 段 > MTU 1420 | 小请求正常、大页面/下载全卡死 | DEPLOY.md §3.5-2（TCPMSS 钳制） |
| `grep 'priority 32764'` 匹配不上 | 每日更新后路由不重灌 | DEPLOY.md §3.5-3 |
| `wg syncconf wg0 -` | 该版本不支持，当成文件名叫 `-` | DEPLOY.md §3.6 |
| `wg set wg0 endpoint` | 报 Invalid argument，必须带 `peer <pubkey>` | DEPLOY.md §3.6 |
| ICMP 通但 WG 打不上握手 | 「在线」节点切过去必失败 | DEPLOY.md §3.6 / WEB-DEPLOY.md §六 |
| 切换后海外全挂、wg0 却有握手 | `ip rule` 的 32764/32765 丢失，流量仍走主表上游网关 | DEPLOY.md §3.2/§七 |
| 以为 `AllowedIPs 0/1+128/1` 写错 | 改成 `0.0.0.0/0` 不解决，反而更依赖 Table 不丢 | DEPLOY.md §3.2 |
| 装 `docker.io` 顺带装了 `ubuntu-fan` | 它投放的 `bind-interfaces` 与 `bind-dynamic` 冲突，dnsmasq 重启即失败 → **全内网 DNS 静默中断** | **DEPLOY.md §七**（2026-11-05 事故）+ `dnsmasq-healthcheck.timer` |
| `dnsmasq --test` 通过就以为配置没问题 | 它只做语法检查，绑定冲突要真正启动才报 | DEPLOY.md §七 |
| 用 `curl -f /api/system/info` 做健康检查 | 未登录返回 **HTTP 200 + code 401**，`-f` 探不出来 | WEB-DEPLOY.md §三 |

---

## 七、回滚

单机没有平台快照，靠**部署前备份**：

```bash
# 部署前把关键状态打包（install.sh 不改 wg0.conf 已有私钥，但配置会被升级）
sudo tar czf /root/route-gw-before-$(date +%Y%m%d).tar.gz \
  /etc/wireguard /etc/dnsmasq.conf /etc/dnsmasq.d /etc/cron.d/route-lists \
  /etc/sysctl.d/99-route-gw.conf /etc/systemd/system/dnsmasq.service.d /usr/local/bin

# 回滚
sudo tar xzf /root/route-gw-before-YYYYMMDD.tar.gz -C /
sudo systemctl daemon-reload
sudo systemctl restart dnsmasq && sudo systemctl restart wg-quick@wg0
```

只想退面板版本：保留 `/opt/gw-admin/data`，覆盖 `/opt/gw-admin/gw_server.py`（`install-web.sh`
会自动把旧后端备份成 `gw_server.py.bak`）即可，不必动网关配置。
