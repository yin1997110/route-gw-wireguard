# 分流网关管理面板 —— 部署与运维文档（装在 LXC 201 里）

> 前置：先按同目录 **DEPLOY.md** 把 201/202 的分流网关装好并验证通过，再来装面板。
> 面板不是独立服务，它读写的是网关本体（`wg0.conf`、策略路由、dnsmasq 配置），
> 网关没跑起来时面板只会显示"未接入节点"。
> 形态：单文件 Python 标准库后端 + 预构建 Vue3 静态产物 + systemd 常驻，全部跑在 201 容器内。

---

## 一、为什么是这个形态（先讲约束，否则设计看起来莫名其妙）

| 约束（201 实测） | 导致的设计 |
|---|---|
| 1 vCore / 512MB 内存 / 2.9GB 空闲磁盘 | 不装 nginx、不装 node 运行时；单进程 stdlib `ThreadingHTTPServer` 直接发静态文件 + API |
| 容器里 **没有** pip3 / npm / nginx / caddy / jq / git / traceroute / ipset | 后端只用 Python 3.12 标准库；前端在**开发机**构建，产物 `dist/` 随包送进去 |
| 面板要改 `/etc/wireguard/wg0.conf`、`/etc/dnsmasq.d/97-panel.conf`，要调 `wg`/`ip`/`iptables`/`systemctl` | 服务必须以 **root** 运行，非特权容器内 root 即够用 |
| 只有一个核，探测/日志不能拖垮转发 | 所有周期任务合并成 5 个后台线程，采样间隔见 `gw_server.py` 顶部常量 |

结论：**"面板 = 一个 py 文件 + 一个 dist 目录 + 一个 service 文件"**，没有别的运行时依赖。

## 二、目录里和面板有关的东西

```
route-gw-deploy/
├── install-web.sh              ← 面板一键安装/升级(幂等，可反复跑)
└── web/
    ├── server/gw_server.py     ← 后端全部逻辑(单文件，约 89KB)
    ├── dist/                   ← 前端构建产物(无需 Node 即可部署)
    ├── gw-admin.service        ← systemd 单元
    ├── app/                    ← 前端源码(Vue3 + Vite + Element Plus)
    │   ├── src/{api,store,views,components,constants,assets,utils,router}
    │   ├── CONTRACT.md         ← 开发契约(目录/常量/组件/样式/扩展点，改动前必读)
    │   ├── ITERATION.md        ← 迭代手册(加一个页面/接口/常量的标准步骤)
    │   └── package.json / vite.config.js / .env
    └── (mock) app/server/mock-server.js ← 离线演示用假后端，只在开发机用
```

装到 201 后的落点：

```
/opt/gw-admin/
├── gw_server.py
├── dist/
└── data/                      ← 面板的全部状态，备份就备这个目录
    ├── credentials.json       账号(salt+PBKDF2-SHA256 12万次迭代，不存明文)
    ├── sessions.json          登录会话(服务重启不掉线)
    ├── config.json            网关参数(WAN/网段/MSS/节点源/查询日志开关…)
    ├── autoswitch.json        自动切换与自愈策略
    ├── nodes.json             节点池(矩阵页同步结果 + 手动节点 + 排除名单)
    ├── rules.json             分流规则与命中计数
    ├── ip_rules.json          面板已下发的 IP 明细路由(用于撤销时对齐)
    ├── subs.json              节点数据源订阅
    ├── events.jsonl           事件日志(追加，上限 EVENT_KEEP)
    ├── traffic.json/series.json  流量统计与曲线
    ├── dns_state.json         dnsmasq log-queries 上次生效状态(决定要不要 restart)
    └── last_switch.json       最近一次切换时刻(冷却期判据)
```

## 三、部署（在 PVE 宿主机上，3 条命令）

```bash
# 0) 先打快照（务必）
pct snapshot 201 pre-web-$(date +%Y%m%d) --description 'install panel before'

# 1) 把整个 route-gw-deploy 目录送进 201
pct push 201 route-gw-deploy.tar.gz /tmp/route-gw-deploy.tar.gz
pct exec 201 -- tar --no-same-owner -xzf /tmp/route-gw-deploy.tar.gz -C /opt

# 2) 安装/升级
pct exec 201 -- bash /opt/route-gw-deploy/install-web.sh
```

可选环境变量（两个都只在**容器内**那层 shell 生效才有用）：

```bash
# 在 201 容器内直接跑
ADMIN_PASSWORD='你自己的密码' bash install-web.sh   # 指定管理员密码(首装和重置都用它)
GW_PANEL_PORT=9000            bash install-web.sh   # 换端口(会自动写 systemd drop-in Environment=GW_PORT=9000)

# 从 PVE 宿主机远程跑：env 必须放在 -- 后面，写成 `ADMIN_PASSWORD=x pct exec 201 -- bash …`
# 只会把变量设到宿主机的 pct 进程上，容器里读不到——这是最容易踩的假成功。
pct exec 201 -- env ADMIN_PASSWORD='你自己的密码' GW_PANEL_PORT=9000 \
    bash /opt/route-gw-deploy/install-web.sh
```

`install-web.sh` 做的事：依赖检查（只要求 python3，缺则 apt 装）→ 备份旧后端 →
投放 `gw_server.py` 并 `py_compile` 校验 → 原子换 `dist/` → 写 systemd 单元并 `enable` →
没有账号文件时创建 `admin` 并**随机生成密码打印一次**（`ADMIN_PASSWORD` 给了就用你的）→
`restart` 服务 → 用"首页 + `/api/user/info`"两个免登录探针自检。

> 自检为什么不用 `/api/system/info`：未登录时它返回的是 **HTTP 200 + code 401**，
> `curl -f` 不会失败，拿它做健康检查等于什么都没测。

看到 `API OK: 面板已在 :8080 提供接口` 后，浏览器打开 `http://<GW_IP>:8080`，
用打印出来的 `admin` / 密码登录。**初始密码只打印这一次**，登录后立刻去「系统设置-账号安全」改。

## 四、登录、会话与账号安全

- 账号只有一个自用管理员 `admin`；密码以 `salt + PBKDF2-HMAC-SHA256(120000 次)` 存
  `data/credentials.json`（权限 600），数据库/接口里永不出现明文。
- 登录后发 cookie `gw_admin_session`（`HttpOnly` + `SameSite=Lax` + 7 天）。会话写进
  `data/sessions.json`，**`systemctl restart gw-admin` 不会把你踢下线**（实测过）。
- 未登录/过期：接口返回 **HTTP 200 + `code:401`**，前端 `src/api/request.js` 的拦截器统一
  跳登录页——这样浏览器控制台不会出现一堆红色 401，也不会漏跳。
- 业务错误同样是 HTTP 200 + 非 200 的 `code` + `msg`，前端弹红条；判断成败要看 `code` 不是看 HTTP 状态。
- 改密码走「系统设置-账号安全」或「右上角头像-修改密码」。**改密成功后服务端会立刻用新密码
  再验一次**（`r_password`），验不过就报失败并记事件——把密码哈希写坏等于把自己锁在门外，宁可报错也不能假装成功。
- **被锁在外面时**（忘记密码 / 改密没成）：
  ```bash
  pct exec 201 -- python3 /opt/gw-admin/gw_server.py --set-password admin '新密码'
  ```
  这条命令直接改 `credentials.json`，不需要旧密码，不依赖服务是否在跑。

## 五、面板与网关的融合点（它到底读写什么）

| 方向 | 对象 | 说明 |
|---|---|---|
| 读 | `wg show wg0 dump` | 接口是否 up、对端公钥/入口、握手时间、收发字节（1 秒缓存，面板多处复用同一次 fork） |
| 读 | `ip rule show` / `ip route` / `ip route show table 51820` | 策略规则条数、国内明细路由条数、隧道表路由 |
| 读 | `iptables -t nat/mangle -S` | NAT/FORWARD/MSS 钳制是否在位 |
| 读 | `dnsmasq --test` + `/etc/dnsmasq.d/*` 行数 | 分流域名数、配置语法 |
| 读 | `journalctl -u dnsmasq.service -f` | 域名规则命中日志（见第八节，本容器 rsyslog 是坏的） |
| 读 | `https://nodes.tbw6.com:3333/data.js` | 节点矩阵（主数据源，后台 300s 醒一次、实际按 6h 节流刷新；手动同步点「立即探测」或 `--sync`） |
| 写 | `/etc/wireguard/wg0.conf` 的 `[Peer]` | 切换节点＝改写公钥+入口，AllowedIPs **恒为** `0.0.0.0/1, 128.0.0.0/1`，绝不跟随节点给的 `0.0.0.0/0` |
| 写 | `wg syncconf` | 平滑换对端：不重建接口、不动策略路由、下挂设备不断网 |
| 写 | `/etc/dnsmasq.d/97-panel.conf` | 「分流规则」里的域名规则编译成 `server=/域名/上游` 或 `address=/域名/` |
| 写 | `ip route replace/del … via WAN / dev wg0 / blackhole` | IP/CIDR 规则的直连、代理、阻断三种动作 |
| 写 | `iptables … <对端IP>/32 dev <WAN>` | anti-loop：换节点后必须把新对端的明文入口重新放行，否则隧道套隧道 |
| 执行 | `systemctl reload|restart dnsmasq`、`systemctl restart wg-quick@wg0` | 「系统设置」的重载/重启按钮 |

面板**只碰 `[Peer]` 这一节**，`[Interface]` 的私钥永不进任何接口响应
（`wg show wg0 dump` 的第 0 行第 0 列就是本机私钥，代码里明确丢弃）。

## 六、切换与自愈的真实语义（这一节是踩坑踩出来的，改代码前务必读）

一次切换（`do_switch`）严格七步，任何一步不成都回滚：

1. 记旧 `wg0.conf` 全文（回滚素材）→ 写新 `[Peer]`（原子写，600）
2. `wg-quick strip wg0` → `wg syncconf wg0 /dev/stdin`
3. **必须检查 syncconf 返回码**：本机 wireguard-tools v1.0.20210914 把 `-` 当文件名，
   `wg syncconf wg0 -` 永远失败。若只喂 `strip` 结果而不看结果，配置文件就跑到了隧道前面，
   之后每次"回滚"还原的都是一个从未生效的版本，`wg0.conf` 与现实永久分叉（这是本项目最贵的一个坑）
4. 补 anti-loop 路由（新对端入口 `/32` 走 WAN）
5. 等握手（`SWITCH_WAIT=8s`）。同公钥换入口时内核会**保留旧握手时间戳**，空闲隧道不会自己
   发起新握手——所以先 `ping -c1` 经隧道踢一个包逼出第一次握手，再接受"时间戳前进**或**落在本窗口内"
   两种情况（后者覆盖重启场景）
6. 用新对端实测一次 `ping` 与出口 IP，写入面板状态
7. 失败 → 还原旧 `wg0.conf` → 再 syncconf → 再补旧对端 anti-loop →**回滚后必须重新实测**

自愈（`maybe_auto_switch`，健康线程每 3s 判定一次）的判据只认实测：

- `dead = 隧道 ping 100% 丢包`；当前节点被判 `fault` 也算；
- **时间戳门控**：`GW.measured_at < LAST_SWITCH_ATTEMPT` 时直接不判——旧对端期间测出来的
  100% 丢包不能用来判刚回滚好的新隧道（实测踩过：回滚成功 2 秒后自愈把健康节点也换走了）；
- 当前对端在节点池里找不到（端点漂移/节点被移出池）时，**隧道通着就不动，实测全丢才另找**；
- 候选排序：同城市 > 同国家 > 跨区域，取延迟最低前 3 个依次试；`groups` 留空=全部 WG 分组；
- 冷却 `cooldown`（默认 300s）内不重复切换；切换失败的目标节点标 `fault` 并 `cfail++`，下轮自动避开。

配置文件与隧道的一致性由三处兜底：

```bash
# 1) 服务启动时：文件跟随隧道（只改文件，绝不动在跑的 peer；wg0 没起来就什么都不做）
python3 /opt/gw-admin/gw_server.py --status | grep 'wg0.conf'     # 应显示"与隧道一致"

# 2) 人工修复（发现分叉时）：以隧道为准重写 wg0.conf
python3 /opt/gw-admin/gw_server.py --restore

# 3) 手工核对（不依赖面板；包里带的脚本，退出码 0=一致 1=分叉）
bash /opt/route-gw-deploy/tools/peer-check.sh
#   conf=203.0.113.10:51820 live=203.0.113.10:51820 文件/隧道=一致 握手距今=122s
```

> **ICMP 通 ≠ 隧道能用**。矩阵页的 alive/延迟是 ICMP 探测结果，同一城市里存在 ping 82~95ms
> 但 WG 端口永不握手的节点（本次 TW_Taiwan_59/.60/.77 就是这样）。所以"可切换"只能由真实握手
> 决定；面板切不过去、8 秒超时回滚，是保护，不是故障。

## 七、面板 CLI 速查（`pct exec 201 -- python3 /opt/gw-admin/gw_server.py …`）

| 命令 | 作用 |
|---|---|
| `--status` | 人读的状态快照：隧道、当前节点、`wg0.conf` 是否与隧道一致、**现测**延迟/丢包/出口、节点池、数据源、规则数、今日流量 |
| `--sync` | 立刻强制同步矩阵节点池（后台线程每 300s 醒一次，但距上次成功不足 `MATRIX_FETCH_INTERVAL`=6h 时会直接跳过，所以手动 `--sync` 才是真刷新） |
| `--probe N` | 探前 N 个节点（默认 40）连通性 |
| `--switch <节点ID>` | 命令行切节点（走和面板完全相同的七步流程） |
| `--restore` | `wg0.conf` 与隧道分叉时以隧道为准重写配置文件，**不动运行中的隧道** |
| `--apply-rules` | 把规则重新编译下发（`97-panel.conf` + IP 明细路由） |
| `--events` | 打印最近事件日志 |
| `--set-password <账号> [新密码]` | 免旧密码重置账号（被锁在外面时用） |

## 八、命中日志为什么读 journal 而不是 `/var/log/syslog`

本容器的 rsyslogd 抢不到由 journald 持有的 `/dev/log`，`/var/log/syslog` 自开机起就没再写入。
面板的命中统计线程因此跟 `journalctl -u dnsmasq.service -f -o short-iso`，
从 `query[A] google.com from 192.168.99.10` 这种行里提域名，按规则优先级匹配后写进
`HITS`（内存滚动，面板重启不追历史）。另外 `log-queries` 是**启动期**选项：
开/关它必须 `systemctl restart dnsmasq`（reload 不生效），面板用 `dns_state.json` 记住上次状态，
只在不一致时才 restart，避免每次存规则都把全网 DNS 抖一下。手工排错同样用
`journalctl -u dnsmasq.service -f`。

## 九、部署后验证清单（照着跑，全绿再收工）

```bash
A=http://127.0.0.1:8080/api
CK=/tmp/chk.ck
curl -s -c $CK -X POST -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<面板密码>"}' $A/login   # 1. 期望 code=200
curl -s -b $CK $A/dashboard/overview | head -c 200            # 2. 有当前节点与今日流量
curl -s -b $CK "$A/node/list?keyword=taiwan" | head -c 200    # 3. 搜索大小写不敏感(总数为 0 就是坏了)
curl -s -b $CK $A/system/tunnel | python3 -m json.tool | head # 4. wgUp=true、endpoint、延迟、策略路由条数
```

逐项确认（每项都应在本轮实测通过）：

| # | 项目 | 期望 |
|---|---|---|
| 1 | 六模块页面 | 仪表盘/节点管理/分流规则/自动切换/系统设置/事件日志都出真实数据，节点表 ~697 行 |
| 2 | 错误密码 | 红条"账号或密码不正确"，不进主界面 |
| 3 | 登出/重登 | 登出有确认；重启 `gw-admin` 后浏览器**仍是登录态**（sessions.json 持久化） |
| 4 | 切换（可达节点） | 1 秒内成功，`wg0.conf` 与隧道同步，出口 IP 跟随新节点，CT202 不断网 |
| 5 | 切换（WG 端口不通的节点） | 8s 超时 → `code=502 … 握手超时，已回滚`，隧道与文件都停在原节点，之后**不应**发生自愈误切 |
| 6 | 自愈 | 封锁当前对端 UDP 后，一个探测周期内换到同区域可用节点，事件里有 `auto_switch/node_up/self_heal` |
| 7 | 域名规则 | 新增后 `/etc/dnsmasq.d/97-panel.conf` 有对应行；CT202 解析该域名 → 规则「命中」列 +1，行内「日志」抽屉有客户端 IP |
| 8 | 删除规则 | `97-panel.conf` 同步移除，CT202 直连/隧道两类站点仍分别 200 |
| 9 | 备份/恢复 | 「导出备份」下载 JSON（含 autoSwitch/config/手动节点/规则/订阅，矩阵节点不打包，重新同步即可）；「恢复备份」**先弹二次确认**，取消不发请求 |
| 10 | 重启网关按钮 | wg0 重建、`ip rule` 5 条、NAT 4 条、国内路由 ~7477 条、CT202 恢复转发 |
| 11 | 开机自启 | `systemctl is-enabled gw-admin wg-quick@wg0 dnsmasq` 全 `enabled`；`pct reboot 201` 后面板自动起 |
| 12 | 私密性 | 任意只读接口响应里都搜不到 `[Interface] PrivateKey`（`--probe`/`--status`/`/system/*` 都核过） |
| 13 | 换端口（可选） | `GW_PANEL_PORT=9000 bash install-web.sh` 后：`systemctl show gw-admin -p Environment` 含 `GW_PORT=9000`、`ss -lntp` 在 9000 上、`curl 127.0.0.1:9000/api/user/info` 回 `code:401`；不带变量再跑一次应回到 8080 且 drop-in 目录被删除 |

## 十、故障处理

| 症状 | 处理 |
|---|---|
| 页面打不开 | `pct exec 201 -- systemctl status gw-admin`；`journalctl -u gw-admin -n 50`；端口被占：`ss -lntp | grep 8080`，install-web.sh 会自己收拾残留 |
| 页面能开、接口 401 | cookie 过期或被清，重新登录；确认没被浏览器按 `SameSite` 拦（用 IP 直接访问最稳） |
| 面板显示节点与 `wg show` 不一致 | 见第六节：先 `--status` 看"wg0.conf 与隧道一致？"，不一致就 `--restore`（以隧道为准重写文件），仍不对再 `systemctl restart wg-quick@wg0` |
| 切换一直 502 | 目标节点 WG 端口不通（ICMP 通不代表能切）。换同组另一个节点，或看 `iptables -S | grep <对端IP>` 确认 anti-loop 在位 |
| 切换后整机断网 | 面板已把原配置写回并 syncconf；若事件里出现"回滚未生效"，**别再点切换**，直接「系统设置-重启网关」重建，事后 `--restore` 对齐文件 |
| 自愈不工作 | 「自动切换」页确认 `启用自愈=开`、`切换冷却`别设太大、`监控分组`包含目标组；`--status` 看当前节点是否被判 fault |
| 规则保存了不生效 | 看行内「已下发」状态与事件日志 `rule_apply` 的 detail；手动 `--apply-rules`；`dnsmasq --test` 查语法；log-queries 变化会 restart，别在高峰期点 |
| 命中日志一直是 0 | `查询日志`开关是否开（「系统设置」）；rsyslog 在本容器不可用，判据看 `journalctl -u dnsmasq`；面板重启后的历史不追 |
| 改了代码但机器上行为没变 | 三种可能：①只 `restart` 没 push 新文件；②`/opt/route-gw-deploy` 还是旧副本，`install-web.sh` 一跑就把版本退回去了；③浏览器缓存。核对 `md5sum /opt/gw-admin/gw_server.py` 与本地包内文件的 md5 是否相同 |
| 忘记/改坏密码 | `--set-password admin '新密码'`（不需要旧密码） |
| 想整体回退 | `pct rollback 201 pre-web-20261031 && pct start 201`（丢掉快照之后的改动，含面板数据） |

## 十一、二次开发（改前端 / 加接口）

前端源码在 `web/app/`，改动前**必读** `web/app/CONTRACT.md`（目录与组件契约、配置抽离、样式变量、
`// EXTENSION_POINT:` 扩展位）与 `web/app/ITERATION.md`（加一个页面/接口/常量的标准步骤）。
红线：不随机重构、不换组件写法、不把常量散写进业务代码、不用内联样式堆页面、不因小改动重写整页。

开发机（有 Node 18+ 的机器，**不是 201**）：

```bash
cd web/app
npm install            # 首次
npm run dev            # 本机预览，接口指向 .env 里的代理目标
npm run build          # 产出 dist/
```

把新产物送进 201（只换前端，不动后端与 data）。下面这段是**在 201 里执行**的
（`--no-same-owner` 必加，否则 Windows 打的 tar 会让容器内 chown 失败，`set -e` 直接中断在半路）：

```bash
set -e
rm -rf /tmp/distnew && mkdir /tmp/distnew
tar --no-same-owner -xzf /tmp/dist.tar.gz -C /tmp/distnew
cd /opt/gw-admin
rm -rf dist.old && mv dist dist.old && mv /tmp/distnew/dist dist
rm -rf dist.old /tmp/distnew
curl -s -o /dev/null -w '首页 %{http_code}\n' http://127.0.0.1:8080/
```

> 后端不用重启就吐新前端（静态文件每次现读），改完刷新浏览器即可。
> 浏览器缓存：入口 JS 文件名带内容 hash，`index.html` 换了就自动拉新包；如果你在
> 同一个标签页里反复验证，地址加 `?t=<随机串>` 绕开缓存。

后端只改 `web/server/gw_server.py` 一个文件。顺序**不能反**（先传后验再重启），下面三条都在宿主机敲：

```bash
pct push 201 web/server/gw_server.py /tmp/gw_server.py           # 1) 送新文件
pct exec 201 -- /bin/bash -c 'sed -i "s/\r$//" /tmp/gw_server.py; python3 -m py_compile /tmp/gw_server.py'  # 2) 去 CRLF + 语法自检
pct exec 201 -- /bin/bash -c 'install -m 644 /tmp/gw_server.py /opt/gw-admin/gw_server.py && systemctl restart gw-admin'  # 3) 落位并重启
pct exec 201 -- python3 /opt/gw-admin/gw_server.py --status       # 4) 冒烟：状态能读出来才算成
```

> ⚠️ 两个坑（本次踩过一次）：
> 1. **只重启不 push** = 改 nothing；`py_compile /opt/gw-admin/gw_server.py` 校验的是**机器上已有的旧文件**。
> 2. `/opt/route-gw-deploy/` 是**上一次解包留下的旧副本**。如果你之后又跑过 `install-web.sh`，
>    它会把后端和前端一起退回那个旧副本的版本。所以：本地改完 → 重新打 `route-gw-deploy.tar.gz` →
>    重新 push+解包 → 再跑 `install-web.sh`。只想临时热修，就走上面 1)~4)，但**别忘了**最终仍要把包同步好。

新增接口在 `routes_table()` 里 `R.append(["GET", r"^/xxx$", h_xxx])`，前端 URL 一律进 `src/api/`，
阈值/路径进 `src/constants/config.js`（前端）与 `gw_server.py` 顶部的 `P/G/D/cfg()`（后端）。

## 十二、安全须知

- 本包不含任何真实私钥或密码（`wg0.conf` 为示例值，密码一律走环境变量传入），可以放心公开。
- 面板默认监听 `0.0.0.0:8080`，**自用场景请只在受信内网开放**；要暴露到公网请先上 TLS/反代并改强密码，
  或直接只监听内网地址：drop-in 写 `Environment=GW_BIND=192.168.99.1`。
- 面板以 root 运行且能重启网关，能登进面板≈能控这台机器；账号只给自己，改密后旧会话仍在
  `data/sessions.json` 里，必要时清掉该文件并 `systemctl restart gw-admin`。
- 备份：`/opt/gw-admin/data` + `/etc/wireguard` + `/etc/dnsmasq.d` + `/usr/local/bin` 四样，
  「系统设置-导出备份」只覆盖面板配置类数据，不含 wg 私钥（私钥在 `/etc/wireguard/wg0.conf`）。
