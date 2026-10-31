# GW-Admin 迭代操作手册

> 配套文档：[CONTRACT.md](./CONTRACT.md)（项目契约，优先级更高）。
> 本手册回答一个问题：**要做某类改动时，改哪几个文件、按什么顺序改、什么绝对不能碰。**
> 版本 v1.0，每次新增一类功能后请回来补一条配方。

---

## 0. 30 秒心智模型

```
视图(views/*)  ──只渲染+派发──▶  store(store/*.js)  ──只调函数──▶  api/*.js  ──URL──▶  后端
      ▲                                │
      └──── 常量 constants/config.js ──┘        样式：assets/css/vars.css(唯一色值来源)
```

- 数据流向永远是 **视图 → store → api**，不允许视图直接 import api 或 axios。
- 视觉调参永远只改 **vars.css**，不允许在 `.vue` 里写十六进制色值。
- 新增功能优先 **加文件 / 加函数 / 加 props（带默认值）**，而不是改写原有实现。

---

## 1. 常见改动配方

### 1.1 新增一个面板页（例：DNS 管理，已落地）

| 步 | 文件 | 动作 |
|---|---|---|
| 1 | `src/views/dns/DnsManage.vue` | **新建**。顶部写 `<!-- 职责: ... -->`，含 `// EXTENSION_POINT:` 注释 |
| 2 | `src/router/index.js` | 在 `appRoutes` 数组追加一条（`path/name/component/meta.title/meta.icon`），菜单自动生成，无需改 Sidebar |
| 3 | `src/api/dns.js` | **新建**，只导出函数，URL 全部以此为前缀 `/dns/...` |
| 4 | `src/store/dns.js` | **新建** Pinia setup-store，持有 list/query 与所有 action，定时器只住这里(`onActivated/onDeactivated` 起停) |
| 5 | `src/constants/config.js` | 若有默认值/枚举，加 `DNS = {...}` 分组 |
| 6 | `server/mock-server.js` | 在 `routes` 数组末尾登记对应端点 |
| 7 | `web/server/gw_server.py` | 在 `routes_table()` 里登记**同名同结构**的端点（少这一步 = 上真机 404） |

多标签页、侧栏菜单、面包屑都会自动出现（由 `router` + `TagsView` + `AppMain` 派生），**不要**去改这三个文件。

### 1.2 给已有页面加一个接口

1. `src/api/<域>.js` 新增函数（命名 `动词+名词`，返回 `request.get/post/...`）。
2. `src/store/<域>.js` 新增 `ref` + `async function`，并把它加进 `return {}` 暴露列表。
3. 视图里 `store.新函数()` 调用。**不要**在视图内 try/catch 弹错误提示（`request.js` 拦截器已统一弹 `ElMessage`）。
4. `server/mock-server.js` 补 mock（真实后端上线后可整体删除 server 目录）。

### 1.3 新增一个公共组件

- 只有 **跨页面复用** 才进 `src/components/`；单页专用组件放该页面同目录（如 `views/rules/RuleGroupDialog.vue`）。
- 组件必须：`props` 传数据、`emits` 抛动作，**内部不发请求、不 import store**。
- 新 props 一律给默认值，保证老调用点不破（向后兼容红线）。
- 在 `CONTRACT.md` 第 3 节表格补一行契约。

### 1.4 新增/调整业务常量

- 只改 `src/constants/config.js`；引用方 `import { XXX } from '@/constants/config'`。
- 枚举 `value` 是与后端对齐的契约值，**只增不改不删**；要改值视为破坏性变更，需同步 mock/后端。

### 1.5 调主题（配色/圆角/动画/密度）

1. `src/assets/css/vars.css`：在 `html.dark` 与 `html.light` 两个块里**成对**加 token。
2. 需要用户可切换 → `src/constants/config.js` 的 `THEME.ACCENTS` 加预设。
3. 写入点只有 `src/store/settings.js` 的 `applyTheme()`；新增可切换维度就在这里加一段 `document.documentElement.style.setProperty`。
4. `src/layout/components/ThemeDrawer.vue` 增加对应控件。
5. 视图层不需要改动。

### 1.6 仪表盘实时数据从轮询换成推送

只改 `src/store/system.js` 的 `startRealtime/stopRealtime`（把 `setInterval` 换成 `WebSocket`/`EventSource`），
视图与图表完全不动。ring buffer 裁剪逻辑（`REFRESH.CHART_WINDOW`）保持不变；
`poll()` 里按 `REFRESH.OVERVIEW_EVERY` 低频补一次 `fetchOverview()`，改推送时记得保留这段（否则"当前节点"卡片会停在入场那一刻）。

### 1.7 对接真实网关 API

本项目**已经**对接完成，实际形态（不要再按"另起 Nginx"的思路改）：

1. 生产后端 `web/server/gw_server.py` 一个进程同时干两件事：`/api/*` 走路由表，其余路径直接吐 `dist/` 静态产物。
   所以前端**不需要**反代，`.env.production` 保持 `VITE_API_BASE_URL=/api` 就是同源。
2. 部署与运维命令在包根的 **WEB-DEPLOY.md**（`install-web.sh`、systemd `gw-admin`、`--status/--sync/--switch/--restore/--set-password`）。
3. `server/mock-server.js` + `scripts/dev.js` 是**开发机离线演示**用，不参与部署，别删也别让它上线。
4. 鉴权是后端 HttpOnly Cookie（`gw_admin_session`）。未登录时后端回 **HTTP 200 + `code:401`**，
   由 `src/api/request.js` 统一跳登录页；业务代码不要各自判 401。

### 1.8 表格行拖拽排序复用到别的列表

`src/utils/dragSort.js` 的 `enableRowDrag(rootEl, { onChange })` 已与业务无关，直接复用：
在目标视图 `onMounted` 里取 `.el-table__body-wrapper` 绑定，`onChange(from,to)` 里算好新 id 顺序后调 store 的 `reorder(...)`，
并在 `onBeforeUnmount` 调用返回的 `dispose()`。拖拽反馈样式沿用 `element-override.css` 的 `.gw-drag-ghost/.gw-drag-chosen`。

### 1.9 改真实后端（`web/server/gw_server.py`）

它只有一个文件、只用标准库，改动步骤：

1. 端点在 `routes_table()` 里注册：`R.append(["GET", r"^/xxx$", fn])`，处理函数签名统一 `(q, b, m)`
   （query / JSON body / 正则匹配）。返回一律用 `ok(data)` / `fail(msg, code)`，不要手写包结构。
2. 需要在响应里带敏感文件内容时**三思**：`/etc/wireguard/wg0.conf` 的 `PrivateKey` 永远不许出接口。
3. 阈值/上限这类值进文件顶部的常量块：`P`（路径/网卡名）、`G`（业务阈值，如 `SERIES_KEEP`、`EVENT_KEEP`）、
   `D`（可被环境变量覆盖的 bind/port/目录/源地址）。函数里不写死数字和路径。
4. 落盘数据统一走 `S.load/S.set_mem`（`data/*.json`）；`set_mem` 是**延迟写盘**的，
   紧接着 `cat` 文件看到旧值不是 bug。
5. 事件用 `push_event(type, message, source=…, detail=…)`；时间字段是**毫秒**，
   前端和探测脚本按毫秒解析（按秒解会显示成 1970）。
6. 部署顺序：`put 新文件 → py_compile 校验刚传上去的文件 → install 到 /opt/gw-admin → systemctl restart gw-admin → --status 冒烟`。
   只 restart 不传文件 = 什么都没改；对 `/opt/gw-admin/gw_server.py` 做 `py_compile` 校验的是旧文件，等于没测。
   另外 `/opt/route-gw-deploy` 是**上次解包的旧副本**：本地改完要先重打 `route-gw-deploy.tar.gz` 并重新 push+解包，
   否则之后任何一次 `install-web.sh` 都会把机器上的版本退回旧包。完整命令见包根 `WEB-DEPLOY.md` 第十一节。
7. 外部命令**只走** `sh(cmd, timeout, shell)`：它永远返回 `(rc, stdout, stderr)` 且不抛异常
   （网关命令失败必须降级，不能让面板整站崩）。要 `shell=True` 时，路径/参数一律
   `shlex.quote()` 之后再拼；不要新写 `subprocess.run`/`os.system`。
8. 视图只渲染和派发；**能碰网关的只有 `gw_server.py`**。前端不允许出现命令拼接或 shell 语义。

---

## 2. 禁改清单（红线，评审对照）

| 对象 | 为什么不能动 |
|---|---|
| `src/api/request.js` 的解包逻辑 | 所有 store 都假设拿到的是 `data`；改成返回整个 body 会全站崩 |
| `vars.css` 里已有 token 的**名称** | 全站上百处 `var(--gw-*)` 引用；只能加新 token 或改值 |
| 公共组件已有 props / emits 的签名 | 只允许新增带默认值的 props；改名等于破坏性重构 |
| store 已导出的 action 名与返回结构 | 视图与后续功能依赖；扩展用新函数 |
| `NODE_STATUS / RULE_TYPES / RULE_ACTIONS / EVENT_TYPES` 的 `value` | 与后端/mock/历史数据三处一致，改值要数据迁移 |
| `router/index.js` 的 `meta.title/icon` 机制 | Sidebar/TagsView/面包屑全靠它派生 |
| 视图的整体结构 | 小改动就地编辑，**禁止**整页重写（红线第 1 条） |

---

## 3. 提交前自检清单

1. 新增文件顶部有 `// 职责:` 或 `<!-- 职责: -->` 说明吗？
2. 页面里有没有魔法数？（`grep -n "[0-9]"` 时能在 `constants/config.js` 找到出处）
3. 页面里有没有硬编码色值 / `style="color:..."`？（动态数值除外）
4. 有没有绕过 store 直接 `import '@/api/xxx'`？
5. 新端点是否同时补进 `server/mock-server.js` 的 `routes` **和** `web/server/gw_server.py` 的 `routes_table()`？
6. 是否新增了 `EXTENSION_POINT` 注释标明后续扩展位？
7. 移动端（<768px）抽屉布局 + 表格横向滚动是否正常？
8. 覆盖类/不可撤销动作前面有 `ConfirmDialog` 吗？确认发生在**执行动作**时，不是选中数据时。
9. 前端校验有没有挡掉后端支持的合法值（空数组、0、留空 = 全部 这类语义）？
10. 涉及搜索的改动，被搜字段和关键字**两边都转小写**了吗？
11. 改了后端的话，`gw_server.py` 是否同步回 `route-gw-deploy/web/server/` 并重启过 `gw-admin`？

---

## 4. 反例（曾想清楚但明确不做的事）

- ❌ 为了"统一"把 6 个视图合并成通用 CRUD 组件——可读性反而下降，页面差异会被塞进一堆 props。
- ❌ 在组件内直接调 api 或读 `import.meta.env`。
- ❌ 用 `!important` 覆盖 Element 主题色；统一走 `element-override.css` 的 CSS 变量。
- ❌ 引入 vuedraggable/sortablejs 之类新依赖来做拖拽（已有零依赖 `utils/dragSort.js`）。

---

## 5. 变更记录（全流程测试中改了什么，为什么）

上线前在 CT201 真实环境跑全流程，改掉的 5 个缺陷。都不是"代码风格"问题，而是**只有连着真网关才会暴露**的行为，
后续加功能时按同样标准自查。

| # | 缺陷 | 触发条件 | 修法 | 落点 |
|---|---|---|---|---|
| 1 | 切换失败回滚后，自愈把刚回滚好的健康节点又换掉 | 手切到一个"ICMP 通但 WG 打不成握手"的对端 → 8s 超时回滚，自愈线程拿着坏对端期间测出的 100% 丢包立刻判定现隧道已死 | 回滚后强制 `wait_handshake()+remeasure()`；新增 `measured_at` 与 `LAST_SWITCH_ATTEMPT` 时间戳闸门，`maybe_auto_switch` 只认"上一次动过 wg0.conf 之后"的读数 | `gw_server.py` `Gateway.remeasure/do_switch/maybe_auto_switch` |
| 2 | 节点搜索搜不到带大写的名字 | `keyword=Taiwan` / `TW_Taiwan_60` 返回 0 行 | 关键字和被搜字段两边都 `.lower()` | `r_node_list` |
| 3 | 事件日志搜索同样漏，且第一次修复写成了不生效的比较 | 同上 | 先拼 `hay` 列表再统一转小写过滤（避免 `%` 优先级把小写只作用在最后一个字段） | `r_event_list` |
| 4 | 订阅源返回"合法 JSON 但不是矩阵结构"时后端抛 KeyError，前端只看到请求失败 | 填一个普通网页地址当节点源 | `meta.cols` 的取值挪进 `try`，缺结构按解析失败处理并 `push_event("sub_fail")` | `matrix_sync` |
| 5 | 选完备份文件**立刻**覆盖全部配置，没有反悔机会 | 系统设置 → 恢复备份 | 选中只做解析，落库前过公共 `ConfirmDialog`（danger 态），确认回调才 `sys.restore()` | `views/system/SystemSetting.vue` |
| 6 | 「监控分组」留空存不下去 | 前端写了"至少选择一个监控分组"，而后端把空数组定义为"纳入全部分组" | 删掉这条伪校验，提示文案改成随选择动态说明两种语义 | `views/autoswitch/AutoSwitchSetting.vue` |

同期修正的部署侧问题（改的是 `install-web.sh`，不在前端契约里，但会坑下一次部署）：

- 自检探测 `/api/system/info` + `curl -f` 永远"通过"——未登录回的是 **HTTP 200 + `code:401`**。改成探首页 `<div id="app">` 和 `/api/user/info` 的 `code` 字段。
- `GW_PANEL_PORT` 只改了提示文案，没传进服务的 `GW_PORT`。改为非默认端口时写 systemd drop-in（`gw-admin.service.d/port.conf`），默认端口时删掉 drop-in。

---

## 6. v1.1 观测批（DNS 管理 / 终端设备 / 切换历史 / 日志查看 / 数据源 / 延迟曲线）

六个只读观测功能，一次加 10 个端点、5 个视图、1 个公共组件。加之前先定了三条边界，后续再加观测页照这三条走：

1. **不动切换与自愈**：新页面没有一条新的下发路径。唯一的写按钮（数据源「立即更新」）调的是网关上
   本来就每天在跑的 `update-lists.sh`，前端只是把它已有的行为露出来。
2. **mock 与真实后端同结构**：每个端点都写成「mock 的 `routes` + 后端的 `routes_table()`」两份，
   并用同一段断言对拍过（分页字段、单位、空值语义必须一致），否则开发机好看、上真机就空表。
3. **只读也要防注入**：日志单元走后端白名单 `G.LOG_UNITS`，DNS 查询域名走正则校验，
   外部命令一律 `sh([...], shell=False)`，绝不把用户输入拼进 shell 字符串。

这一批里只有连着真网关/真实事件流才会暴露的问题，都改掉了：

| # | 问题 | 现象 | 根因与修法 |
|---|---|---|---|
| 1 | 切换历史时间/耗时单位错 | 时间显示成 1970，平均耗时 6880.9「秒」 | 事件 `time` 本来就是**毫秒**；`at` 直接取 `e["time"]`，`cost` 用 `(结果-发起)/1000` 保留一位。前端一律按毫秒 `fmtTime` |
| 2 | 切换历史被探测噪声填满 | 一次切换出现 3~4 行，"成功"和"无结果"混在一起 | 不带 `to` 的 `node_down/node_up` 是判故障/恢复探测，不是切换动作 → 排除；带 `to` 的 `self_heal` 若是 60s 内已配对切换的汇总 → 也排除（只有"自愈未执行"这种无 `to` 的保留为一次失败） |
| 3 | 终端设备列表把面板自己算一台设备 | 局域网设备多出一个 `127.0.0.1` | `parse_query_line` 过滤回环来源：本机探测和 dnsmasq 自检不是局域网设备 |
| 4 | 分组筛选器缺项 | 节点数千，切到第 2 页后下拉里只剩本页的分组 | `/api/node/list` 额外回全量 `groups`（不随分页变化），前端优先用它、缺失时才按本页推导 |
| 5 | 矩阵地址写死在前端常量 | 仓库脱敏后页面显示占位地址，用户以为数据源坏了 | `/api/node/list` 回 `nodeSource`（后端 `cfg()` 优先，兜底 `D["MATRIX"]`），前端常量只当兜底文案 |
| 6 | 日志查看器出现双时间戳 | 每行开头两个时间 | journal 单元由后端拆出 `t`/`text`，视图只渲染 `t`；文件单元（lists 日志）`t` 为 null 显示 `—`，不再把整行原文再拼一遍 |
| 7 | mock 里 `nodeSource`/`latency`/`loss` 与真机不一致 | 演示页看着对，接口对拍失败 | mock 的事件补 `ago` 回填时间、逐事件带自己的 `latency/loss`（不再抄当前节点），配对逻辑与后端同源 |

> 加观测页时最容易犯的错：**在视图里直接起 `setInterval`**。轮询一律进 store，
> 页面用 `onActivated` 起、`onDeactivated` 停（keep-alive 下 `onUnmounted` 根本不会触发）。

