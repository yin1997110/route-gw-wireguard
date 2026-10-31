# GW-Admin 分流网关管理后台 · 项目契约文档

> 版本 v1.0 | 本文档是开发的最高约束，任何迭代必须与本文档同步更新。
> 配套阅读：[ITERATION.md](./ITERATION.md)（迭代操作手册）

## 0. 技术栈与运行

- Vue 3 (script setup) + Vite + Pinia + Vue Router + Element Plus + ECharts + Axios + dayjs
- 后端契约：REST JSON `{ code: 200, data, msg }`，前缀 `/api`，dev 由 Vite 代理到零依赖 Mock（`server/mock-server.js:8931`）
- 运行：`npm run dev`（自动同时拉起 mock），生产替换 `VITE_API_BASE_URL` 即可对接真实网关 API
- **生产后端 = `web/server/gw_server.py`**（Python 标准库单文件，跑在 CT201，systemd 单元 `gw-admin`，默认 `0.0.0.0:8080`）。
  它和 mock 走**同一套端点与响应结构**，前端不需要区分环境；改端点时两边都要改（见 §4）。
- **鉴权**：会话是后端下发的 HttpOnly Cookie（`gw_admin_session`），前端不持 token、不落 localStorage。
  未登录访问受保护端点时后端返回 **HTTP 200 + `code: 401`**（不是 401 状态码），由 `request.js` 拦截器
  统一跳登录页；因此**探测脚本不能用 `curl -f` 判活**，只能探首页或读 `code` 字段。
  免鉴权白名单：`/login`、`/logout`、`/user/info`。

## 1. 目录文件结构（若依规范，新增文件必须落位对应目录）

```
gw-admin/
├── CONTRACT.md / ITERATION.md          契约与迭代手册
├── package.json / vite.config.js / index.html / .env*
├── scripts/dev.js                      dev 启动器（前端+mock 一起拉起）
├── server/mock-server.js               零依赖 Mock 后端（Demo 数据源）
├── src/
    ├── main.js  App.vue                入口
    ├── constants/config.js             ★业务常量唯一来源（禁止在业务代码散落魔法数）
    ├── api/                            ★接口层唯一入口（页面禁止写 URL/直接用 axios）
    │   ├── request.js                  axios 实例+拦截器（统一 code 解包/报错）
    │   ├── dashboard.js  node.js  rule.js  subscription.js
    │   ├── event.js      system.js     dns.js  client.js
    ├── store/                          ★Pinia 全局状态（业务逻辑主要归属层）
    │   ├── app.js                      侧栏折叠/设备类型(移动检测)
    │   ├── settings.js                 主题模式/强调色/实时刷新间隔(localStorage)
    │   ├── tagsView.js                 多标签页
    │   ├── nodes.js                    节点 CRUD/切换/订阅刷新/导入导出
    │   ├── rules.js                    规则组/规则 CRUD/拖拽排序/命中日志
    │   ├── dns.js                      DNS 总览/上游/命中样本(观测，只读)
    │   ├── clients.js                  客户端设备列表(观测，只读)
    │   ├── lists.js                    数据源(国内 IP 明细/gfwlist)状态与更新日志
    │   ├── logs.js                     日志查看器(服务日志 + 命中日志)
    │   ├── switchlog.js                切换历史(发起↔结果配对)
    │   └── system.js                   仪表盘时序/实时轮询/事件日志/系统操作/延迟序列
    ├── router/index.js                 路由表（meta: title/icon/affix/hidden）
    ├── layout/                         布局壳（不属于业务页面）
    │   ├── index.vue                   侧栏/抽屉切换 + 顶栏 + 标签 + 内容区
    │   └── components/ Sidebar.vue Navbar.vue TagsView.vue AppMain.vue
    │                   ThemeDrawer.vue ThemeDrawerTrigger.vue
    │                   ※ Navbar 常驻当前节点徽章并持有全局节点轮询；
    │                     ThemeDrawer 实例由 ThemeDrawerTrigger 自带，布局不再重复挂载
    ├── components/                     ★全局公共组件（跨页面复用才放这里）
    │   ├── StatusTag.vue               状态标签(在线/离线/故障/切换中)
    │   ├── DelayBadge.vue              延迟徽章(按阈值自动分级着色)
    │   ├── SpeedChart.vue              上/下行时序图(ECharts 封装,主题自适应)
    │   ├── LatencyChart.vue            延迟/丢包时序图(仪表盘与切换历史共用)
    │   └── ConfirmDialog.vue           危险操作确认(带 loading)
    ├── views/                          业务视图，一个菜单页一个目录
    │   ├── dashboard/index.vue         仪表盘
    │   ├── nodes/NodeList.vue          节点管理
    │   ├── rules/RuleManage.vue        分流规则
    │   ├── autoswitch/AutoSwitchSetting.vue  自动切换&自愈
    │   ├── dns/DnsManage.vue           DNS 管理(上游/分流域名/命中样本)
    │   ├── clients/ClientList.vue      客户端设备(谁在走哪条路)
    │   ├── switchlog/SwitchHistory.vue 切换历史(耗时/结果/原因)
    │   ├── logs/LogViewer.vue          日志查看器(服务日志与命中日志)
    │   ├── lists/DataSource.vue        数据源面板(国内 IP 明细/gfwlist)
    │   ├── events/EventLog.vue         事件日志
    │   └── system/SystemSetting.vue    系统设置
    ├── utils/                          纯函数工具（无状态）
    │   ├── format.js                   字节/速率/时长/时间格式化
    │   └── dragSort.js                 表格行拖拽排序(HTML5 原生，供任意列表复用)
    └── assets/css/
        ├── vars.css                    ★全部色值/阴影/圆角/动画参数(CSS变量)
        ├── base.css                    全局基础样式 + .gw-card 等布局类
        └── element-override.css        Element Plus 微调（只允许用 var() 覆盖）
```

## 2. 全局常量清单（`src/constants/config.js`）

| 分组 | 常量 | 默认值 | 用途 |
|---|---|---|---|
| APP | APP.NAME / APP.VERSION | 分流网关 / 1.0.0 | 标题/关于 |
| PAGINATION | PAGE_SIZE / PAGE_SIZES | 10 / [10,20,50,100] | 所有表格 |
| PROBE | PROBE.INTERVAL / TIMEOUT / FAIL_THRESHOLD | 30s / 3s / 3次 | 健康探测默认参数 |
| PROBE | PROBE.TYPES | tcping, ping | 探测方式 |
| SWITCH | SWITCH.COOLDOWN | 300s | 自动切换冷却 |
| SWITCH | SWITCH.SAME_REGION_FIRST | true | 切换优先同国家/城市 |
| TRAFFIC | TRAFFIC.RESET_DAY | 1 | 流量月重置日 |
| REFRESH | REFRESH.REALTIME_INTERVAL / CHART_WINDOW / OVERVIEW_EVERY | 2s / 120点 / 5轮 | 仪表盘采样窗口；每 5 轮顺带刷新概览卡片 |
| REFRESH | REFRESH.NODE_POLL | 5s | 节点列表全局轮询(Navbar 启停，store 单例计时) |
| NODE_SOURCE | APP.NODE_SOURCE_HOME | https://matrix.example.com:3333 | 节点主数据矩阵（**仓库里是占位值**；真实地址由 `/api/node/list` 的 `nodeSource` 回传，前端优先用它） |
| SUBSCRIPTION | SUBSCRIPTION.AUTO_FETCH / FETCH_INTERVAL_HOURS | true / 24h | 订阅定时拉取 |
| DNS | DNS.TYPES / VIEWS / HIT_LIMIT / HIT_POLL | A,AAAA / 四视图 / 40 / 5s | DNS 管理页的查询类型、对比视图与命中流水 |
| CLIENT_VIEW | POLL / RECENT | 10s / 4 | 客户端设备页轮询间隔、行内展开的最近查询条数 |
| SWITCH_RESULT | success/fail/rollback/pending | — | 切换历史的结果枚举，value 与 `gw_server.switch_result()` 一一对应 |
| LOGS | LINES / DEFAULT_LINES / POLL | [100,200,400] / 200 / 15s | 日志查看器行数与轮询（日志源白名单在后端 `G.LOG_UNITS`） |
| LIST_VIEW | POLL | 60s | 数据源页状态轮询（脚本本体由 cron/`update-lists.sh` 跑） |
| DELAY | DELAY.GOOD / DELAY.BAD | 150ms / 400ms | DelayBadge 分级阈值 |
| DELAY | DELAY.LOSS_MILD / LOSS_BAD | 1% / 10% | 丢包降级阈值(丢包≥10% 直接判红) |
| LAYOUT | LAYOUT.MOBILE_BP | 768px | 视口 ≤ 该值侧栏转抽屉 |
| ENUM | RULE_TYPES / RULE_ACTIONS / RULE_PATTERN_RE / NODE_STATUS / EVENT_TYPES | 见文件 | 下拉与状态枚举 |
| THEME | THEME.MODES / THEME.ACCENTS / THEME.STORAGE_KEY | dark,light; 5色 | 主题抽屉选项与持久化键 |

页面里出现数字阈值 = 违规，必须从这里导入。

## 3. 公共组件契约（props/emits 是唯一接口，不得内部发请求）

| 组件 | props | emits | 说明 |
|---|---|---|---|
| StatusTag | `status: String(NODE_STATUS)` | — | 圆点+文案，在线带呼吸动画 |
| DelayBadge | `delay: Number, loss?: Number` | — | <GOOD 绿 <BAD 黄 其余红，null 显示 — |
| SpeedChart | `points: Array<{t,up,down}>`, `height?: String` | — | ECharts 封装，主题切换自动重绘；EXTENSION: 可加 series 配置 |
| ConfirmDialog | `modelValue, title, text, danger?, loading?` | `confirm`, `update:modelValue` | 危险操作统一入口 |

## 4. API 模块 ↔ 端点清单

| 模块 | 函数 | 端点 |
|---|---|---|
| auth | login / logout / getUserInfo / changePassword | POST /api/login, /api/logout, GET /api/user/info, POST /api/system/password |
| dashboard | getOverview / getRealtime / getLatency | GET /api/dashboard/overview, /realtime, /latency |
| node | listNode / addNode / updateNode / delNode / switchNode / exportNode / importNode | /api/node/* |
| rule | listRuleGroup / addRuleGroup / delRuleGroup / listRule / addRule / updateRule / delRule / reorderRule / listRuleHit | /api/rule/* |
| subscription | listSub / fetchSub / addSub / delSub | /api/subscription/* |
| event | listEvent / clearEvent / listSwitchHistory | /api/event/*, GET /api/switch/history |
| system | getSysInfo / getTunnel / reloadGw / restartGw / getBackup / restoreBackup / getConfig / putConfig / getAutoSwitch / putAutoSwitch / probeNow / changePassword / getLogUnits / getLogs | /api/system/* |
| dns | getOverview / getUpstream / listQuery | /api/dns/overview, /api/dns/query, /api/dns/hits |
| client | listClient | /api/client/list |
| list（数据源） | getStatus / update | /api/list/status, /api/list/update |

新增/改动端点时，`src/api/*.js`、`server/mock-server.js` 的 `routes`、`web/server/gw_server.py` 的
`routes_table()` 三处必须同步，否则前端在 mock 下能跑、上真机 404。

**观测类端点一律只读**；唯一的写型观测端点是 `POST /api/list/update`，它只调用网关上已存在的
`update-lists.sh`（与 cron 同一入口），不新造任何下发路径。切换/自愈逻辑没有任何新增入口。

## 5. Store 契约

- **组件只做：渲染 store 状态 + 派发 store action**。store 内部调 api/ 层并处理错误后的派发动作。
- 定时器只允许住在 store 里，且必须是"先 stop 再 start"的单例：`system.startRealtime/stopRealtime`(REALTIME_INTERVAL) 与 `nodes.startPoll/stopPoll`(NODE_POLL)。
- 页面在 keep-alive 下**必须用 `onActivated/onDeactivated`** 绑定取数与轮询，不要用 onMounted/onUnmounted（离开页面不会 unmount，会把轮询留在后台）。全局节点轮询由布局(Navbar onMounted/onUnmounted)持有，视图不另起定时器。
- 表单提交统一 `const ok = await formRef.value.validate().catch(() => false); if (!ok) return`；直接 `await validate()` 会在校验失败时抛出未捕获的 rejection。
- 节点不可达(离线/故障/切换中)时后端返回 `delay: null` 而不是 0；前端一律交给 DelayBadge 渲染成 `—`，排序用 `delay ?? 1e9` 兜底。
- `settings.applyTheme()` 是主题唯一写入口：dark/light class + 强调色变量（含 Element 主色）。

## 6. 路由与菜单

路由即菜单（`meta.hidden` 隐藏），顺序：dashboard / nodes / rules / autoswitch / dns / clients /
switchlog / logs / lists / events / system。
新页面 = router/index.js 的 `appRoutes` 数组新增一项 + views 下新建目录，其余不动。

## 7. 样式与主题红线

1. 所有颜色/阴影/圆角/动画时长**只能**来自 `assets/css/vars.css` 的 CSS 变量；组件内 style 用 `var(--gw-*)`。
2. 主题两套 token 通过 `html.dark` / `html.light` 切换；强调色写入 `--gw-accent`（Element 主色由 settings.js 同步）。
3. 页面独有样式放视图文件 `<style scoped>`，命名 `.页面名-*`；禁止无意义 class。
4. 内联 style 仅允许动态值（如进度条百分比 width），颜色禁止内联。
5. 唯一允许出现在 JS 里的色值是 `constants/config.js` 的 `THEME.ACCENTS`（用户可选预设，属于数据不是样式）；其余色值一律进 vars.css。

## 8. 扩展点位（代码中以 `// EXTENSION_POINT:` 注释标记）

| 位置 | 预留方向 |
|---|---|
| router appRoutes | 新面板页（已落：DNS 管理、客户端设备、切换历史、日志查看、数据源） |
| constants/config.js ENUM 区 | 新规则类型(如 keyword/suffix)、新事件类型 |
| views/nodes/NodeList.vue toolbar | 节点分组列、测速历史、矩阵页对接 |
| views/rules/RuleManage.vue | 规则模板库、批量启停、正则校验扩展 |
| store/system.js realtime | 换 WebSocket/SSE 推送（仅改该文件） |
| components/SpeedChart.vue | series 可配置化、多指标叠加 |
| components/LatencyChart.vue | 多目标延迟对比（同一条曲线图换 series 即可） |
| views/dns/DnsManage.vue | 上游按运营商/地区分组、自定义 hosts 条目管理 |
| views/clients/ClientList.vue | 每设备流量占比、按设备绑定分流规则 |
| views/switchlog/SwitchHistory.vue | 切换失败原因聚合统计、按节点维度看成功率 |
| views/logs/LogViewer.vue | 关键字高亮、多单元并排、日志下载 |
| views/lists/DataSource.vue | 数据源更新时间线、明细条目搜索 |
| layout/components/ThemeDrawer.vue | 圆角/密度/字号等新主题 token |
| utils/dragSort.js | 任意表格行拖拽排序复用（节点排序、订阅源排序） |
| views/rules/RuleManage.vue 分组侧栏 | 分组重命名/排序/图标 |
| store/system.js switchEvents | 切换记录改为后端分页、通知回调（已由 /api/switch/history 承担） |
| server/mock-server.js | 新增端点唯一注册处 `routes` 数组 |
| utils/format.js | 新格式化函数一律加这里，不进组件 |

## 9. 禁止行为（红线，评审时逐条对照）

- ❌ 随机重构已有代码；小改动全盘重写页面
- ❌ 更换既有组件写法（例如把 store action 挪回组件、把 Options API 混进 script setup）
- ❌ 配置/魔法数散落业务代码
- ❌ 页面直接 fetch/axios、硬编码 URL
- ❌ 硬写色值、大量内联样式
- ❌ 新增功能改写公共组件签名（扩展用新增 props/函数，保持向后兼容）
- ❌ 覆盖类/不可撤销操作（恢复备份、删除、重启网关）不走 `ConfirmDialog` 就直接执行——
  「选完文件立刻覆盖全量配置」就是这类事故，确认要在**动作前**，不是选中数据时
- ❌ 前端校验拦掉后端合法状态（例：`监控分组` 留空 = 纳入全部分组，是后端支持的语义，
  前端却写「至少选一个」会让某个正常配置永远存不下）
- ❌ 搜索/过滤只把关键字转小写、不把被搜字段转小写（结果：`TW_Taiwan_60` 这类带大写的名字永远搜不到）
