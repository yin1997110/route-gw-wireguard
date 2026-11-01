# route-gw — 同网段单臂旁路由（WireGuard 策略路由分流）+ 管理面板

单台非特权 LXC 容器（只有一块 LAN 网卡）搞定分流：国内 IP 段直连、其余走隧道；DNS 按域名分流；
主表默认路由全程不动。**同网段任意主机只要把「默认网关 + DNS」都指向 201 就自动跟随分流**，
不需要第二块网卡、不需要改客户端路由表，也没有写死 201 的 IP/网段。

自带零依赖管理面板（单文件 Python 标准库后端 + Vue3 前端），负责节点切换、数据源状态展示和配置/隧道一致性自愈。节点在线与延迟由数据源扫描提供，本机不再逐节点探测。

> 环境：PVE 9.1.1（宿主机 `<PVE_HOST>`）· LXC **201 = router/旁路由**（单网卡 eth0 + 面板）· LXC **202 = client**（同网段测试机）
> 系统：Ubuntu 24.04 非特权容器 · WireGuard 对端示例段 `203.0.113.0/24`（RFC 5737 文档地址，换成你自己的节点）
> 本目录是**自包含**的：换一套环境也能照着文档从零重建。201/202 均已实测「重启自恢复」「换 IP 后自动跟随」。

---

## 一、README 怎么读 / 按什么顺序做

| 你要做什么 | 读哪个文件 |
|---|---|
| 只搭分流网关（网络层） | **DEPLOY.md**（一→五节照跑即可） |
| 网关之上再装管理面板 | DEPLOY.md 做完 → **WEB-DEPLOY.md** |
| 把现有 CT201 整套搬到一台原生 Ubuntu 主机 | **MIGRATE.md** |
| 看迁移后的实测结果/性能/重启恢复 | **TEST-REPORT.md** |
| 自建/修改节点数据源，或对接 data.js 格式 | **MATRIX-FORMAT.md** |
| 让 LAN 客户端访问 ZeroTier/Tailscale 网络 | **OVERLAY.md** |
| 只想快速上手 | 本文下面的「三、快速开始」 |
| 改前端代码 / 加功能 | **web/app/CONTRACT.md**（开发契约）+ **web/app/ITERATION.md**（怎么迭代） |
| 排障 | DEPLOY.md 第七节 · WEB-DEPLOY.md 第十节 |

**部署顺序是固定的：网关 → 面板。** 面板读网关的运行状态（wg0、策略路由、dnsmasq、数据源），网关没起来时面板只能显示空壳。反向（先装面板）不会报错，但验证做不完。

---

## 二、目录导航

```
route-gw-deploy/
├── README.md                  ← 本文：总入口
├── DEPLOY.md                  ← 网关部署文档（架构原理 + 一步步命令 + 验证标准）
├── WEB-DEPLOY.md              ← 面板部署文档（部署/登录/与网关融合点/换节点语义/运维）
├── MIGRATE.md                 ← 把 CT201 整套搬到一台原生 Ubuntu 主机（含 AppArmor 坑）
├── TEST-REPORT.md             ← 迁移后的 0.x 客户端 / Docker Registry / 大文件 / 强制重启报告
├── MATRIX-FORMAT.md           ← data.js 节点源格式约定（自建内网源/数据包）
├── OVERLAY.md                 ← LAN 客户端访问 ZeroTier/Tailscale 的 NAT 方案
├── install.sh                 ← 在 201 内以 root 执行：一键装网关（8 步，幂等）
├── install-zerotier.sh        ← 安装 ZeroTier、加入网络（ID 由参数传入）并启用 overlay NAT
├── install-web.sh             ← 在 201 内以 root 执行：一键装/升面板（幂等，不覆盖 data/）
├── setup-202.sh               ← 在 202 内以 root 执行：客户端 DNS/网关对接（只有两件事）
├── files/                     ← 要落到容器里的配置文件原文（ wg0.conf 是示例值，私钥需自填 ）
│   ├── etc/wireguard/wg0.conf
│   ├── etc/dnsmasq.conf
│   ├── etc/dnsmasq.d/00-listen.conf       ← DNS 监听接口（跟随默认路由网卡）
│   ├── etc/dnsmasq.d/98-custom-domain.conf
│   ├── etc/cron.d/route-lists
│   ├── etc/sysctl.d/99-route-gw.conf
│   ├── etc/systemd/system/dnsmasq.service.d/override.conf
│   ├── etc/apparmor.d/local/wg-quick      ← Ubuntu 26.04+ 放行 PostUp/PostDown 钩子
│   └── usr/local/bin/{wg-route-up.sh, wg-route-down.sh, update-lists.sh}
├── tools/                     ← 辅助脚本（ssh_run/upload/rexec/portforward 只用 paramiko；两个 .sh 零依赖）
│   ├── ssh_run.py             paramiko SSH：`host "<cmd>"` / `ct <vmid> "<cmd>"` / `push <vmid|-> <本地> <远端>`
│   ├── rexec.py               `run <vmid|-> <脚本>`（base64 送进去跑，绕开引号地狱）/ `put` / `get`
│   ├── upload.py              base64-over-ssh 传文件（容器禁 sftp 时用）
│   ├── portforward.py         `--local 18080 --remote <GW_IP>:8080` 本机浏览器调试用的端口转发
│   ├── netcheck-202.sh        客户端全面体检，在 202 上 `bash` 直接跑
│   └── peer-check.sh          核对 wg0.conf 的对端 与 隧道真实对端 是否分叉，在 201 上跑
└── web/                       ← 管理面板
    ├── app/                   Vue3 + Element Plus 前端源码（含 CONTRACT.md / ITERATION.md / mock-server.js）
    │   └── dist/              已经构建好的静态产物 —— 没有 Node 环境也能直接部署
    ├── server/gw_server.py    单文件后端，纯 Python 标准库，直接跑在 201 上
    └── gw-admin.service       systemd 单元
```

容器内的落位（部署后）：

| 包内位置 | 容器内位置 | 说明 |
|---|---|---|
| `files/etc/**` | `/etc/**` | 网关配置，权限由 install.sh 设置（wg0.conf 600） |
| `files/usr/local/bin/*.sh` | `/usr/local/bin/` | 755，install 时 `sed 's/\r$//'` 去 CRLF |
| `web/server/gw_server.py` | `/opt/gw-admin/gw_server.py` | 后端本体 |
| `web/app/dist/` | `/opt/gw-admin/dist/` | 前端静态产物（vite 构建输出，随包分发） |
| `web/gw-admin.service` | `/etc/systemd/system/gw-admin.service` | `systemctl enable --now gw-admin` |
| — | `/opt/gw-admin/data/*.json(l)` | **运行数据**（节点池/规则/订阅/事件/会话/状态），升级安装不动它 |

---

## 三、快速开始（在 PVE 宿主机上按序执行）

前提：201/202 容器已按 DEPLOY.md 第二节在 PVE 侧创建好，本目录已放到 201 的 `/opt/`。

```bash
# 0) 打包（开发机 Git Bash 里，本目录的上一级执行）
tar czf route-gw-deploy.tar.gz route-gw-deploy

# 1) 送进 201 并解包（--no-same-owner 必加：Windows 打的 tar 带 Windows uid）
pct push 201 route-gw-deploy.tar.gz /tmp/route-gw-deploy.tar.gz
pct exec 201 -- tar --no-same-owner -xzf /tmp/route-gw-deploy.tar.gz -C /opt

# 2) 装网关（会装包、起隧道、灌 ~7400 条国内路由、拉数据源，约 2~4 分钟）
#    GW_GFW_DNS 是隧道内境外 DNS，写到 /etc/default/route-gw，不落仓库
pct exec 201 -- env GW_GFW_DNS='<隧道内DNS>' bash /opt/route-gw-deploy/install.sh

# 3) 装管理面板（不给密码就随机生成一个并打印在终端）
#    注意 ADMIN_PASSWORD 要用 `pct exec … -- env` 传，写在 pct 前面只会设到本机进程上
pct exec 201 -- env ADMIN_PASSWORD='换成你的密码' GW_GFW_DNS='<隧道内DNS>' \
  bash /opt/route-gw-deploy/install-web.sh

# 4) 客户端 202（网关已在 PVE 侧指向 201；这里只改 DNS + 自检）
pct push 202 route-gw-deploy/setup-202.sh /opt/setup-202.sh
pct exec 202 -- bash /opt/setup-202.sh
```

装完用 DEPLOY.md 第五节（网关矩阵）和 WEB-DEPLOY.md 第九节（面板自检）逐条验收。
浏览器开 `http://<201的LAN地址>:8080`，用 `admin` + 上面的密码登录。

**同网段任意主机接入**：在网络设置里把「默认网关」和「DNS」都填成 201 的 LAN 地址
（面板「系统设置 → 旁路由接入」会直接显示这个地址）。两个都必须指向 201；只改网关会让域名分流失效。

---

## 四、🔐 机密处理须知（先看完再动手）

本包**不含任何真实机密**，可以放心公开：`wg0.conf` 里的私钥留空、对端公钥与入口都是占位符，文档里的地址
统一用 `<PVE_HOST>` / `<GW_IP>` / `203.0.113.x`（RFC 5737 文档保留段）替代。真实值只在你部署时填进
**自己那台机器**，别写回这个仓库。

1. WG 密钥自己生成：`wg genkey` 出私钥、`wg pubkey` 出公钥；`PublicKey`/`Endpoint` 从你的服务商处拿。
   落到容器里权限 600，且不要把改过的 `wg0.conf` 提交回来。
   **`install.sh` 升级时不会覆盖已有的 `/etc/wireguard/wg0.conf`**，避免把在用的私钥冲成占位值；
   确需重置示例配置时才用 `FORCE_WG_CONF=1 bash install.sh`。
2. PVE / LXC 的 root 密码**不写进本目录**：`tools/ssh_run.py`、`tools/upload.py`、`tools/rexec.py`、
   `tools/portforward.py` 统一从环境变量取，没设就直接报错——
   `export PVE_PW='...'` 之后再调用。（四个工具共用 `ssh_run.py` 里的那一处读取。）
   宿主机地址走 `PVE_HOST`（`ssh_run.py` 里的默认值是占位符 `<PVE_HOST>`，必须覆盖才能用）。
3. 面板管理员密码：`install-web.sh` 打印出来的那个 / 你传入的 `ADMIN_PASSWORD`。
   库里存的是 PBKDF2-SHA256(120000 次) 哈希（`/opt/gw-admin/data/credentials.json`），**不落明文**。
   唯一的例外是首次启动自动生成的随机密码，会写一份 `data/INITIAL_PASSWORD.txt`（权限 600）；
   `install-web.sh` 走的是自己生成→打印→删除这条路径，所以装完机上不留明文文件。
   想清楚一件事：**能登面板 ≈ 能 root 201**（可改策略路由、可重启 wg-quick/dnsmasq）。

**泄露了怎么办**：换 WG 密钥（在服务商侧重新签发 → 改 `wg0.conf` → `systemctl restart wg-quick@wg0`）；
改面板密码（页面「系统设置 → 账号安全」，或忘了密码就在 201 上
`python3 /opt/gw-admin/gw_server.py --set-password admin '新密码'`，这条只改哈希、不写明文文件）。

另外：面板的「备份导出」JSON 里含手动节点/规则/订阅/账号哈希，但**不含 WG 私钥**；
`/etc/wireguard/wg0.conf` 只读进、不写出，接口响应里永远不会出现 `PrivateKey`。
调试时也别顺手 `wg showconf wg0`——它会把私钥原样打到终端上（本文档的排错命令都刻意避开了它）。

---

## 五、这套东西到底是什么

- **分流网关（201，单臂旁路由）**：三层配合 —— 策略路由规则 + 国内 IP 明细路由（IP 层）+ gfwlist 域名 DNS 劫持（域名层）。
  国内 IP 走 `eth0` 直连，其余走 `wg0`；同网段客户端（202/手机/PC）的网关/DNS 都指向 201，所以自动跟随分流。
  客户端流量从 eth0 进来、转发后仍从 eth0（直连）或 wg0（隧道）出去，NAT 按运行时算出的 LAN 网段做。
- **管理面板（也在 201）**：Vue3 前端（预构建静态产物）+ 单文件 Python 标准库后端 + systemd 常驻。
  左侧菜单 11 页：**仪表盘 / 节点管理 / 分流规则 / 自动切换与自愈 / DNS 管理 / 客户端设备 / 切换历史 /
  日志查看 / 数据源 / 系统设置 / 事件日志**。前 6 页是可操作的日常刚需，后 5 页是观测面（只读，
  或复用已经验证过的下发路径），负责把「解析走向、谁在上网、切换花了几秒、隧道哪一层出问题」摊开在屏上。
  节点主数据来自矩阵订阅源，换节点是「写 `wg0.conf` → `wg syncconf` → 等握手 → 实测 → 不达标就回滚」七步，
  失败不会把隧道留在坏状态。
- **约束决定了形态**：201 只有 1 核 512MB、没有 node/npm/pip/nginx/jq/git。
  所以后端不用任何第三方库、前端预构建、`dist` 直接随包分发。

---

## 六、已踩过的坑（文档里都有对应章节，这里只给索引）

| 坑 | 表现 | 见 |
|---|---|---|
| `tar` 带 Windows uid | 解包 chown 报错 | 上面第三节 |
| Ubuntu 模板首启残留交互式 apt | `Could not get lock` | DEPLOY.md §3.5-5 / §七 |
| PostUp 时 `wg show endpoints` 为空 | anti-loop 路由静默漏加 | DEPLOY.md §3.5-1 |
| 对端 DF 段 > MTU 1420 | 小请求正常、大页面/下载全卡死 | DEPLOY.md §3.5-2（TCPMSS 钳制） |
| `grep 'priority 32764'` 匹配不上 | 每日更新后路由不重灌 | DEPLOY.md §3.5-3 |
| 容器内直接改网络/DNS 文件 | 重启被 PVE 覆盖 | DEPLOY.md §2.3（必须 `pct set`） |
| `pct snapshot 201 list` | 真建了个叫 `list` 的快照 | DEPLOY.md §2.4 |
| `wg syncconf wg0 -` | 该版本不支持，当成文件名叫 `-` | DEPLOY.md §3.6 |
| `wg set wg0 endpoint` | 报 Invalid argument，必须带 `peer <pubkey>` | DEPLOY.md §3.6 |
| ICMP 通但 WG 打不上握手 | 「在线」节点切过去必失败 | DEPLOY.md §3.6 / WEB-DEPLOY.md §六 |
| 大量「连续 ICMP 无回包」 | 旧版本本机逐节点探测的误判；现在节点状态由数据源扫描提供 | DEPLOY.md §3.6-5 |
| 当前节点 ICMP 失败就自动切 | 会反复重建 WG 会话；现在只认隧道 2 次 100% 丢包 + 握手超时 | DEPLOY.md §3.6-5 |
| 回滚后不重测延迟 | 自愈拿着坏对端期间的 100% 丢包，把刚回滚好的健康节点也换掉 | WEB-DEPLOY.md §六 |
| 切换后海外全挂、wg0 却有握手 | `ip rule` 的 32764/32765 丢失，流量仍走主表 `.1` | DEPLOY.md §3.2/§七 · TEST-REPORT.md §七 |
| 以为 `AllowedIPs 0/1+128/1` 写错 | 改成 `0.0.0.0/0` 不解决，反而更依赖 Table 不丢 | DEPLOY.md §3.2 |
| 用 `curl -f /api/system/info` 做健康检查 | 未登录返回 **HTTP 200 + code 401**，`-f` 探不出来 | WEB-DEPLOY.md §三 |

---

## 七、回滚

部署前后各有快照（在 PVE 宿主机 `pct listsnapshot 201` 查看）：

```bash
pct rollback 201 pre-deploy-20261030 && pct start 201   # 回到网关部署前
pct rollback 201 pre-web-20261031    && pct start 201   # 回到面板部署前（网关配置保留）
pct rollback 202 pre-deploy-20261030 && pct start 202   # 202 同名两份快照，按需回退
```

> 201 和 202 上这两份快照名字完全一样，`pct listsnapshot <vmid>` 可核对。

> 回滚会丢掉快照点之后的数据（含面板里手动加的节点/规则）。只想退面板版本的话，
> 用 `/opt/gw-admin/data` 保留 + 覆盖 `/opt/gw-admin/gw_server.py` 就够，不必回滚容器。
