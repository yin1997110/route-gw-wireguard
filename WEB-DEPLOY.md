# 分流网关管理面板 —— 部署与运维文档

> 装在同一台网关机上（J1900 / Ubuntu 26.04），与 `wg-quick@wg0`、`dnsmasq` 共处一个系统。
> 前置：先按 **DEPLOY.md** 把分流网关装好并验收通过，再来装面板。
> 面板不是独立服务，它读写的是网关本体（`wg0.conf`、策略路由、dnsmasq 配置），
> 网关没跑起来时面板只会显示「未接入节点」。
> 节点数据源 `data.js` 的格式见 **MATRIX-FORMAT.md**；LAN 客户端访问 ZeroTier/Tailscale 见 **OVERLAY.md**。

---

## 一、为什么是这个形态（先讲约束，否则设计看起来莫名其妙）

| 约束（J1900 实测） | 导致的设计 |
|---|---|
| 4 核 / 8GB，无 nginx、无 node 运行时 | 不装 nginx；单进程 stdlib `ThreadingHTTPServer` 直接发静态文件 + API |
| 机上没有 pip3 / npm / nginx / jq / git | 后端只用 Python 3 标准库；前端在**开发机**构建，产物 `dist/` 随包分发 |
| 面板要改 `/etc/wireguard/wg0.conf`、`/etc/dnsmasq.d/97-panel.conf`，要调 `wg`/`ip`/`iptables`/`systemctl` | 服务以 **root** 运行 |
| 转发是主业，探测/日志不能拖垮它 | 周期任务合并成少量后台线程，采样间隔见 `gw_server.py` 顶部常量 |

结论：**面板 = 一个 py 文件 + 一个 dist 目录 + 一个 service 文件**，没有别的运行时依赖。

---

## 二、目录里和面板有关的东西

| 包内位置 | 落位 | 说明 |
|---|---|---|
| `web/server/gw_server.py` | `/opt/gw-admin/gw_server.py` | 后端本体（~130KB，纯标准库） |
| `web/app/dist/` | `/opt/gw-admin/dist/` | 前端静态产物（vite 构建输出） |
| `web/gw-admin.service` | `/etc/systemd/system/gw-admin.service` | systemd 单元（`GW_PORT` 默认 8080） |
| `web/app/` | 不落位 | 前端源码，只在开发机上用 |
| `install-web.sh` | — | 安装/升级脚本（幂等） |
| — | `/opt/gw-admin/data/` | **运行数据**：节点池、规则、订阅、事件、会话、状态、`credentials.json` |

---

## 三、部署（3 条命令）

```bash
# 1) 备份（建议）
sudo tar czf /root/gw-admin-before-$(date +%Y%m%d).tar.gz /opt/gw-admin/data 2>/dev/null

# 2) 安装/升级（首次会自动生成管理员密码并打印在终端）
sudo ADMIN_PASSWORD='换成你的密码' GW_GFW_DNS='<隧道内DNS>' \
  bash /opt/route-gw-deploy/install-web.sh

# 3) 浏览器打开
echo "http://<GW_IP>:8080"
```

`install-web.sh` 做 6 件事：依赖检查（python3/curl）→ 目录与旧后端备份 → 投放后端并
`py_compile` 校验 → 投放前端 `dist`（先把旧目录改名再切换）→ 写 systemd 单元与 drop-in →
设置管理员密码并启动、自检。

### 接入信息走 drop-in，不写进代码

真实环境值都在 `/etc/systemd/system/gw-admin.service.d/site.conf`：

```ini
[Service]
Environment=GW_MATRIX_URL=https://<数据源域名>/data.js
Environment=GW_GFW_DNS=<隧道内DNS>
Environment=GW_WG_SRC=10.14.0.2
```

换端口用 `GW_PANEL_PORT=9000 bash install-web.sh`，会生成 `port.conf`（与 `site.conf` 互不覆盖）。

> 这些值**不要提交回仓库**；仓库里的 `web/gw-admin.service` 只有通用默认值。

---

## 四、登录、会话与账号安全

- 账号 `admin`，密码是你传入的 `ADMIN_PASSWORD`，或首次随机生成的 16 位（只在终端打印一次）。
- 库里存 `PBKDF2-SHA256(120000 次)` 哈希：`/opt/gw-admin/data/credentials.json`（600），**不落明文**。
- 会话：登录成功下发 `HttpOnly; SameSite=Lax` 的 cookie，TTL 由后端 `SESSION_TTL` 决定。
- 登录失败有 IP 限流（10 分钟内失败过多返回 429，并记 `login` 事件）。
- 改密：页面「系统设置 → 账号安全」，或命令行
  `python3 /opt/gw-admin/gw_server.py --set-password admin '新密码'`。

> **能登面板 ≈ 能 root 这台机**：面板可改策略路由、可重启 `wg-quick@wg0` / `dnsmasq`。
> 不要把 8080 暴露到公网；远程访问请用 SSH 隧道或只在 LAN 内使用。

---

## 五、面板与网关的融合点（它到底读写什么）

### 读

| 来源 | 用途 |
|---|---|
| `wg show wg0 dump` | 当前 peer、握手时间、收发字节 |
| `/etc/wireguard/wg0.conf` | 当前节点配置（**只读，不写出私钥**） |
| `ip rule show` / `ip route show table 51820` | 分流规则是否在位（自愈依据） |
| `systemctl is-active wg-quick@wg0` / `dnsmasq` | 服务状态 |
| `/etc/dnsmasq.d/99-gfw.conf`、`98-custom-domain.conf` | 域名规则条数/内容 |
| `/proc/net/dev`、`/proc/meminfo`、`/proc/stat` | 流量、内存、CPU |
| 数据源 `data.js` | 节点池、在线状态、延迟（本机不再逐节点探测） |

### 写

| 目标 | 触发 |
|---|---|
| `/etc/wireguard/wg0.conf` | 切节点、修复分叉（`--restore`） |
| `/etc/dnsmasq.d/97-panel.conf` | 「分流规则」页增删域名 |
| `/opt/gw-admin/data/*.json(l)` | 节点池、订阅、事件、切换历史、状态快照 |

### 接口清单

路由表在 `gw_server.py` 的 `routes_table()` 里注册，前缀统一 `/api`：

- 公开：`POST /api/login`、`POST /api/logout`、`GET /api/user/info`
- 仪表盘：`GET /api/dashboard/overview`、`GET /api/dashboard/realtime`
- 其余按功能前缀：`/api/node/*`、`/api/rule/*`、`/api/dns/*`、`/api/client/*`、
  `/api/subscription/*`、`/api/event/*`、`/api/log/*`、`/api/system/*`、`/api/switch/*`

> **鉴权陷阱**：未登录时后端返回 **HTTP 200 + `{"code":401}`**（让前端自己跳登录），
> 所以 `curl -f` 探不出「未登录」，健康检查要用 `/api/user/info` 且看 `code` 字段。

---

## 六、切换与自愈的真实语义（改代码前务必读）

### 切换七步（失败不会把隧道留在坏状态）

1. 从节点池取目标节点（含 `server`/`pubkey`/端口）；
2. 备份当前 `wg0.conf`；
3. 写新 `[Peer]` 到 `wg0.conf`；
4. `wg-quick strip wg0 | wg syncconf wg0 /dev/stdin`（私钥不落盘；见 DEPLOY.md §3.6）；
5. 等握手（约 8 秒超时）；
6. 隧道内实测（延迟/丢包）；
7. 不达标 → 回滚到备份配置并重测，再试下一个候选。

### 一致性自愈

- **服务启动时**：文件跟随隧道（只改文件，绝不动在跑的 peer；`wg0` 没起来就什么都不做）。
- **人工修复**（发现分叉）：`python3 /opt/gw-admin/gw_server.py --restore` 以隧道为准重写 `wg0.conf`。
- **策略路由自愈**：`health_loop` 每 3 秒检查 `ip rule` 的 32764/32765 是否在位，缺了自动补回。
- **手工核对**：`bash /opt/route-gw-deploy/tools/peer-check.sh`，退出码 0=一致、1=分叉，
  输出形如 `conf=203.0.113.10:51820 live=203.0.113.10:51820 文件/隧道=一致 握手距今=122s`。

### 自动切换的触发条件

必须**连续 2 次**隧道 100% 丢包（约 30s）**且**最近握手 >120s 才切；单个节点 ICMP 失败不触发。
节点「在线」状态由数据源扫描提供，不是本机 ping 结果。

---

## 七、面板 CLI 速查

```bash
python3 /opt/gw-admin/gw_server.py --status       # 当前节点/隧道/规则摘要
python3 /opt/gw-admin/gw_server.py --sync         # 立即同步数据源矩阵
python3 /opt/gw-admin/gw_server.py --switch <节点ID>
python3 /opt/gw-admin/gw_server.py --restore      # 以隧道为准重写 wg0.conf
python3 /opt/gw-admin/gw_server.py --apply-rules  # 重新下发 dnsmasq 规则
python3 /opt/gw-admin/gw_server.py --events       # 最近事件
python3 /opt/gw-admin/gw_server.py --set-password admin '新密码'
```

---

## 八、命中日志为什么读 journal 而不是 `/var/log/syslog`

dnsmasq 的 `log-queries` 输出进 journal；本机 `/var/log/syslog` 常因 rsyslog 没拿到 `/dev/log`
而是空的。所以面板「日志查看」读的是 `journalctl -u dnsmasq`，不是文件。

```bash
journalctl -u dnsmasq --no-pager | tail -50
journalctl -u gw-admin --no-pager | tail -50
journalctl -t dns-health --no-pager | tail -20     # DNS 自愈记录
```

---

## 九、部署后验证清单（照着跑，全绿再收工）

```bash
systemctl is-active gw-admin                       # active
ss -lntp | grep 8080                               # python3 在听
curl -fsS http://127.0.0.1:8080/ | grep -q '<div id="app">'   # 静态产物就位
curl -fsS http://127.0.0.1:8080/api/user/info      # 未登录也应返回 JSON（code 401）
journalctl -u gw-admin -n 30 --no-pager            # 无 Traceback
systemctl is-active wg-quick@wg0 dnsmasq           # 网关侧仍正常
```

浏览器侧逐页点一遍：仪表盘有数据 → 节点列表能同步 → 切换一个节点能回滚/成功 →
分流规则页能增删 → 事件日志有记录。

---

## 十、故障处理

| 症状 | 排查 |
|---|---|
| 打不开 8080 | `systemctl status gw-admin`；`journalctl -u gw-admin -n 50`；端口被占（`ss -lntp \| grep 8080`） |
| 页面空白 | `/opt/gw-admin/dist/index.html` 是否存在；`install-web.sh` 是否报「缺 dist」 |
| 登录一直失败 | `data/credentials.json` 是否存在/权限；`--set-password` 重置；查 `login` 事件是否被限流 |
| 面板显示未接入节点 | `wg show wg0` 是否真有 peer；`peer-check.sh` 是否分叉 |
| 切换后海外全挂 | 看 `ip rule` 32764/32765 是否在（面板 3 秒自愈）；再 `python3 gw_server.py --restore` |
| 节点显示在线但切不过去 | 该节点 WG 端口不通；切换会 8s 超时自动回滚，属正常保护 |
| 面板重启后节点变了 | 启动时会「文件跟随隧道」，以 `wg show wg0 dump` 为准 |
| 升级后数据没了 | `/opt/gw-admin/data` 不应被覆盖；检查是否误删 |

---

## 十一、二次开发（改前端 / 加接口）

```bash
cd web/app
npm install
npm run dev            # 本地 mock-server + vite，不碰真实网关
npm run build          # 产物进 dist/，随包分发
```

- 前端契约见 `web/app/CONTRACT.md`，迭代约定见 `web/app/ITERATION.md`；
- 后端加接口：在 `routes_table()` 里追加 `["GET", r"^/xxx$", handler]`，返回统一 `ok(...)` / `fail(...)`；
- 改完跑 `python3 -m py_compile gw_server.py`，再 `install-web.sh` 部署。

---

## 十二、安全须知

- 面板只监听 LAN（或按需绑 `127.0.0.1` + SSH 转发），**不要**在路由器上给 8080 做端口映射。
- `ADMIN_PASSWORD` 只通过环境变量/终端输入，不写进脚本、不提交。
- 备份导出 JSON 含手动节点/规则/订阅/账号哈希，**不含 WG 私钥**；导出文件自己保管好。
- `/etc/wireguard/wg0.conf` 权限 600；任何情况下不要在终端 `wg showconf wg0`（会打印私钥）。
