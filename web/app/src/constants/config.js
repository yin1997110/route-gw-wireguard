// 职责: 业务常量唯一来源。改默认行为只改这里；页面/组件禁止散落魔法数。
// EXTENSION_POINT: 新增探测类型/规则动作/事件类型时，在 ENUM 区扩展，并保持 value 稳定(后端契约)。

// ---- APP ----
export const APP = {
  NAME: '分流网关',
  VERSION: '1.0.0',
  NODE_SOURCE_HOME: 'https://nodes.tbw6.com:3333' // 矩阵主数据页(仅"来源说明"展示与打开)
}

// ---- 布局 ----
export const LAYOUT = { MOBILE_BP: 768 } // 视口 ≤ 该值按移动端处理(侧栏转抽屉)

// ---- 表格分页 ----
export const PAGINATION = { PAGE_SIZE: 10, PAGE_SIZES: [10, 20, 50, 100] }

// ---- 健康探测 ----
export const PROBE = {
  // WireGuard 端口是 UDP，TCP 连接必然失败，唯一可信的探测是绕过策略路由的 ICMP
  TYPES: [
    { value: 'ping', label: 'ICMP Ping' }
  ],
  INTERVAL: 30,          // 秒
  TIMEOUT: 3,            // 秒
  FAIL_THRESHOLD: 3      // 连续失败 N 次判定故障
}

// ---- 自动切换 ----
export const SWITCH = {
  COOLDOWN: 300,         // 切换冷却(秒)
  SAME_REGION_FIRST: true // 优先切换同国家/城市节点
}

// ---- 流量 ----
export const TRAFFIC = { RESET_DAY: 1 }

// ---- 实时刷新 ----
export const REFRESH = {
  REALTIME_INTERVAL: 2, // 实时采样间隔(秒)
  CHART_WINDOW: 120, // 曲线滚动窗口点数
  NODE_POLL: 5, // 节点列表全局轮询(秒)
  OVERVIEW_EVERY: 5 // 每 N 次实时采样顺带刷新概览(当前节点/流量卡)
}

// ---- 订阅 ----
export const SUBSCRIPTION = { AUTO_FETCH: true, FETCH_INTERVAL_HOURS: 24 }

// ---- 延迟分级(DelayBadge 用)。loss 为 0~1 小数 ----
export const DELAY = { GOOD: 150, BAD: 400, LOSS_MILD: 0.01, LOSS_BAD: 0.1 }

// ---- ENUM: 业务枚举(值与后端对齐，禁止随意改名) ----
export const NODE_STATUS = {
  ONLINE: { value: 'online', label: '在线', tag: 'success' },
  OFFLINE: { value: 'offline', label: '离线', tag: 'info' },
  FAULT: { value: 'fault', label: '故障', tag: 'danger' },
  SWITCHING: { value: 'switching', label: '切换中', tag: 'warning' }
}
export const RULE_TYPES = [
  { value: 'domain', label: '域名', placeholder: 'example.com / *.example.com' },
  { value: 'ip', label: 'IP/CIDR', placeholder: '1.2.3.4 或 10.0.0.0/8' },
  { value: 'geoip', label: 'GeoIP', placeholder: 'CN / US / HK' }
]
export const RULE_ACTIONS = [
  { value: 'direct', label: '直连', tag: 'success' },
  { value: 'proxy', label: '代理(隧道)', tag: 'primary' },
  { value: 'reject', label: '阻断', tag: 'danger' }
]
export const RULE_PATTERN_RE = /^[*a-zA-Z0-9.\-_/:\u4e00-\u9fa5]+$/
export const EVENT_TYPES = [
  { value: 'node_up', label: '节点上线', tag: 'success' },
  { value: 'node_down', label: '节点下线', tag: 'danger' },
  { value: 'auto_switch', label: '自动切换', tag: 'warning' },
  { value: 'manual_switch', label: '手动切换', tag: 'primary' },
  { value: 'self_heal', label: '自愈', tag: 'warning' },
  { value: 'rule_apply', label: '规则下发', tag: 'success' },
  { value: 'sub_fetch', label: '订阅拉取', tag: 'info' },
  { value: 'sub_fail', label: '订阅失败', tag: 'danger' },
  { value: 'login', label: '登录鉴权', tag: 'info' },
  { value: 'sys_op', label: '系统操作', tag: 'info' }
]

// ---- 登录鉴权 ----
// 会话为后端 HttpOnly Cookie，前端不存 token；401 由 request.js 统一跳转 LOGIN_PATH
export const AUTH = {
  LOGIN_PATH: '/login',
  WHITE_LIST: ['/login'],        // 免鉴权路由
  MIN_PASSWORD: 8,               // 改密最短长度(与后端 r_password 对齐)
  USER_HOME: '/dashboard',       // 登录成功后落地页
  PASSWORD_PAGE: '/system'       // "修改密码"菜单跳转的页面
}

// ---- 主题 ----
export const THEME = {
  MODES: [
    { value: 'dark', label: '深色科技' },
    { value: 'light', label: '明亮' }
  ],
  ACCENTS: [
    { value: '#4c9aff', name: '极光蓝' },
    { value: '#00d68f', name: '翡翠绿' },
    { value: '#9c6bff', name: '电紫' },
    { value: '#ff8f4c', name: '落日橙' },
    { value: '#ff5c8a', name: '霓虹粉' }
  ],
  STORAGE_KEY: 'gw-admin-settings'
}
