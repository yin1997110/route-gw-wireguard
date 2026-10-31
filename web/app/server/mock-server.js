// 职责: 零依赖 Mock 后端(node:http)，为 Demo 提供与 src/api 契约完全一致的假数据。
// 端口 8931，Vite 代理 /api → 本服务。上线接真实网关时整目录可直接删除，前端代码无需改动。
// 鉴权：与生产 gw_server 同构的 Cookie 会话，演示账号 admin / gw123456。
// EXTENSION_POINT: 新增接口时在 routes 表登记，保持与 src/api/*.js 一一对应。
import http from 'node:http'

const PORT = Number(globalThis.process?.env?.MOCK_PORT || 8931)
const WRAP = (data, msg = 'ok') => ({ code: 200, data, msg })
const FAIL = (msg, code = 500) => ({ code, data: null, msg })

const now = () => Date.now()
const rnd = (min, max) => min + Math.random() * (max - min)
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)]
let seq = 1000
const nextId = () => ++seq

// ---------------- 数据源 ----------------
// 新增节点统一构造: 客户端携带的 id 一律作废，避免与既有节点冲突
const mkNode = (o) => {
  const { id: _drop, ...rest } = o || {}
  return {
    status: 'offline', delay: null, loss: 0, upBytes: 0, downBytes: 0,
    lastCheck: now(), current: false, baseDelay: 120, ...rest, id: nextId()
  }
}
const NODE_SEED = [
  ['洛杉矶', '美国', '🇺🇸', 'HK-优化', 142, 'us-lax-01.tbw6.com'],
  ['圣何塞', '美国', '🇺🇸', 'HK-优化', 158, 'us-sjc-02.tbw6.com'],
  ['纽约', '美国', '🇺🇸', 'US-原生', 96, 'us-nyc-03.tbw6.com'],
  ['东京', '日本', '🇯🇵', 'HK-优化', 78, 'jp-tyo-01.tbw6.com'],
  ['大阪', '日本', '🇯🇵', 'JP-原生', 85, 'jp-osa-02.tbw6.com'],
  ['香港', '中国香港', '🇭🇰', 'HK-优化', 42, 'hk-hkg-01.tbw6.com'],
  ['九龙', '中国香港', '🇭🇰', 'HK-优化', 55, 'hk-kln-02.tbw6.com'],
  ['台北', '中国台湾', '🇹🇼', 'HK-优化', 68, 'tw-tpe-01.tbw6.com'],
  ['新加坡', '新加坡', '🇸🇬', 'HK-优化', 88, 'sg-sin-01.tbw6.com'],
  ['首尔', '韩国', '🇰🇷', 'KR-原生', 92, 'kr-sel-01.tbw6.com'],
  ['法兰克福', '德国', '🇩🇪', 'EU-原生', 232, 'de-fra-01.tbw6.com'],
  ['伦敦', '英国', '🇬🇧', 'EU-原生', 248, 'uk-lon-01.tbw6.com'],
  ['阿姆斯特丹', '荷兰', '🇳🇱', 'NL-原生', 214, 'nl-ams-02.tbw6.com'],
  ['温哥华', '加拿大', '🇨🇦', 'US-原生', 168, 'ca-yvr-01.tbw6.com'],
  ['悉尼', '澳大利亚', '🇦🇺', 'AU-原生', 176, 'au-syd-01.tbw6.com']
]

const db = {
  nodes: NODE_SEED.map(([city, country, flag, group, baseDelay, server], i) => ({
    id: i + 1,
    name: `${flag} ${city} ${i % 2 ? '0' + (2 + (i % 3)) : '01'}`,
    server, port: pick([51820, 443, 8443, 23760]),
    group, country, city, flag,
    status: 'online', baseDelay, delay: baseDelay, loss: 0,
    upBytes: Math.round(rnd(2, 30) * 1024 ** 2),
    downBytes: Math.round(rnd(20, 320) * 1024 ** 2),
    lastCheck: now() - Math.round(rnd(1, 25)) * 1000,
    current: i === 5
  })),
  groups: [
    { id: 1, name: '默认组' },
    { id: 2, name: 'AI-服务' },
    { id: 3, name: '流媒体' }
  ],
  rules: [
    { id: 1, groupId: 1, type: 'geoip', pattern: 'CN', action: 'direct', remark: '国内 IP 直连', enabled: true, hits: 182340, lastHit: now() - 4000 },
    { id: 2, groupId: 1, type: 'domain', pattern: '*.github.com', action: 'proxy', remark: '代码托管', enabled: true, hits: 9821, lastHit: now() - 62000 },
    { id: 3, groupId: 1, type: 'ip', pattern: '192.168.0.0/16', action: 'direct', remark: '内网', enabled: true, hits: 45120, lastHit: now() - 15000 },
    { id: 4, groupId: 2, type: 'domain', pattern: 'openai.com', action: 'proxy', remark: '', enabled: true, hits: 3311, lastHit: now() - 30000 },
    { id: 5, groupId: 2, type: 'domain', pattern: 'chatgpt.com', action: 'proxy', remark: '含子域', enabled: true, hits: 12043, lastHit: now() - 8000 },
    { id: 6, groupId: 2, type: 'domain', pattern: 'anthropic.com', action: 'proxy', remark: '', enabled: false, hits: 12, lastHit: now() - 86400000 },
    { id: 7, groupId: 3, type: 'domain', pattern: 'youtube.com', action: 'proxy', remark: '含 cdn 域', enabled: true, hits: 8890, lastHit: now() - 21000 },
    { id: 8, groupId: 3, type: 'domain', pattern: 'netflix.com', action: 'reject', remark: '区域限制，直接阻断', enabled: false, hits: 3, lastHit: now() - 3600000 }
  ].map((r) => ({ ...r, priority: r.id })),
  subs: [
    { id: 1, name: '机场主订阅', url: 'https://nodes.tbw6.com:3333/sub/aaaa', autoFetch: true, lastFetch: now() - 3600_000 * 5 },
    { id: 2, name: '备用订阅', url: 'https://nodes.tbw6.com:3333/sub/bbbb', autoFetch: false, lastFetch: now() - 86400_000 * 2 }
  ],
  events: [],
  config: {
    wanIf: 'eth0', wanGw: '192.168.1.1', lanCidr: '192.168.99.0/24', wgLan: '10.14.0.2/16',
    mssClamp: true, listUpdateAt: '04:30', chinaRouteCount: 7461, gfwDomainCount: 4372
  },
  autoSwitch: {
    enabled: true, probeType: 'ping', interval: 30, timeout: 3, failThreshold: 3,
    cooldown: 300, sameRegionFirst: true, groups: ['HK-优化', 'US-原生'], resetDay: 1
  }
}

// ---------------- 事件流 ----------------
function pushEvent(type, message, extra = {}) {
  db.events.unshift({
    id: nextId(), time: now(), type, message,
    source: extra.source || '自动自愈', from: extra.from, to: extra.to,
    reason: extra.reason, detail: extra.detail || JSON.stringify(extra, null, 2)
  })
  if (db.events.length > 300) db.events.length = 300
}
pushEvent('sys_op', '网关服务启动，加载策略路由 3 条 / 国内明细 7461 条', { source: '系统' })
pushEvent('manual_switch', `手动切换到 🇭🇰 香港 01`, { from: '🇹🇼 台北 01', to: '🇭🇰 香港 01', reason: '用户操作' })
pushEvent('auto_switch', '🇯🇵 东京 01 连续 3 次探测失败，已切换至 🇭🇰 九龙 02', { from: '🇯🇵 东京 01', to: '🇭🇰 九龙 02', reason: 'TCPing 超时 (丢包 100%)' })
pushEvent('sub_fetch', '订阅「机场主订阅」拉取成功，新增 3 个节点', { source: '订阅' })
pushEvent('node_down', '🇩🇪 法兰克福 01 离线', { reason: '握手超时' })

// ---------------- 实时模拟 ----------------
let tick = 0
const cur = () => db.nodes.find((n) => n.current) || db.nodes[0]
const baseOf = (n) => n.baseDelay ?? NODE_SEED.find((s) => s[0] === n.city)?.[4] ?? 120
function simulate() {
  tick++
  db.nodes.forEach((n) => {
    if (n.status === 'switching') return
    const target = baseOf(n)
    n.baseDelay = target
    if (n.status !== 'online') { n.delay = null; n.loss = 1; n.lastCheck = now(); return }
    n.delay = Math.max(10, Math.round(target + rnd(-12, 16)))
    n.loss = Math.round(rnd(0, 20)) / 100
    n.lastCheck = now()
    if (Math.random() < 0.006) {
      n.status = 'fault'; n.delay = null; n.loss = 1
      pushEvent('node_down', `${n.name} 探测失败判定故障`, { reason: `连续 ${db.autoSwitch.failThreshold} 次 TCPing 超时`, detail: `${n.server}:${n.port} loss=100%` })
      if (!n.current && db.autoSwitch.enabled) tryAutoSwitch(n)
    } else if (Math.random() < 0.004) {
      n.status = 'fault'; n.delay = null; n.loss = 1
      pushEvent('node_down', `${n.name} 离线`, { reason: '握手超时' })
    }
  })
  db.nodes.filter((n) => n.status === 'fault' && Math.random() < 0.08).forEach((n) => {
    n.status = 'online'
    n.delay = baseOf(n)
    pushEvent('node_up', `${n.name} 恢复在线`, { reason: `延迟回落至 ${n.delay}ms` })
  })
}
function tryAutoSwitch(bad) {
  const pool = db.nodes.filter((n) => !n.current && n.status === 'online' && db.autoSwitch.groups.includes(n.group))
  if (!pool.length) return
  const same = db.autoSwitch.sameRegionFirst ? pool.filter((n) => n.country === bad.country) : []
  const target = (same.length ? same : pool).sort((a, b) => (a.delay ?? 1e9) - (b.delay ?? 1e9))[0]
  const prev = cur()
  prev.current = false
  target.current = true
  pushEvent('auto_switch', `${bad.name} 故障，自动切换至 ${target.name}`, {
    from: bad.name, to: target.name,
    reason: same.length ? '同区域优先命中' : '跨区域最优延迟'
  })
}
setInterval(simulate, 2000)

function speed() {
  const c = cur()
  const base = 6.2 * 1024 * 1024
  const down = Math.max(0.4e6, base * (0.55 + 0.42 * Math.sin(tick / 7)) + rnd(-1.4e6, 1.8e6))
  return { down: Math.round(down), up: Math.round(down * rnd(0.06, 0.14)), cpu: rnd(6, 26), mem: rnd(38, 58), latency: c.delay }
}
const series = Array.from({ length: 60 }, (_, i) => {
  const s = speed()
  return { t: now() - (60 - i) * 2000, up: s.up, down: s.down }
})

// ---------------- 工具 ----------------
function paginate(rows, { pageNum = 1, pageSize = 10 } = {}) {
  const p = Math.max(1, Number(pageNum))
  const size = Math.max(1, Number(pageSize))
  return { rows: rows.slice((p - 1) * size, p * size), total: rows.length }
}
const EXIT_IPS = ['62.197.157.46', '185.108.107.12', '103.135.212.30']
function nodeView(n) {
  return { ...n, exitIp: n.current ? EXIT_IPS[0] : undefined }
}

// ---------------- 路由表 ----------------
// ---- 鉴权(Mock 简化：明文密码 + 固定 Cookie，仅用于本地演示) ----
const AUTH = { user: 'admin', pass: 'gw123456', cookie: 'gw_admin_session', sid: 'mock-session' }
const isAuthed = (req) => new RegExp(`${AUTH.cookie}=${AUTH.sid}\\b`).test(req.headers.cookie || '')
const PUBLIC_API = [/^\/login$/, /^\/logout$/, /^\/user\/info$/]

const routes = [
  ['POST', /^\/login$/, (q, body) => {
    if (body?.username !== AUTH.user || body?.password !== AUTH.pass) return FAIL('账号或密码不正确', 401)
    return WRAP({ username: AUTH.user }, '登录成功')
  }],
  ['POST', /^\/logout$/, () => WRAP(true, '已退出')],
  ['GET', /^\/user\/info$/, (q, body, m, req) =>
    isAuthed(req) ? WRAP({ username: AUTH.user }) : FAIL('未登录', 401)],
  ['POST', /^\/system\/password$/, (q, body, m, req) => {
    if (!isAuthed(req)) return FAIL('未登录', 401)
    if (body?.oldPassword !== AUTH.pass) return FAIL('原密码不正确', 403)
    if ((body?.newPassword || '').length < 8) return FAIL('新密码至少 8 位')
    AUTH.pass = body.newPassword
    return WRAP(true, '密码已更新')
  }],

  // 仪表盘
  ['GET', /^\/dashboard\/overview$/, () => {
    const n = cur()
    return WRAP({
      node: { ...nodeView(n), uptime: Math.floor((now() - bootAt * 1000) / 1000) },
      meta: {
        todayUp: 412 * 1024 ** 2, todayDown: 5.8 * 1024 ** 3,
        monthUp: 12.4 * 1024 ** 3, monthDown: 168.7 * 1024 ** 3,
        peakUp: 14.2 * 1024 ** 2, peakDown: 11.6 * 1024 ** 2,
        nodeCount: db.nodes.length, onlineCount: db.nodes.filter((x) => x.status === 'online').length,
        groupCount: new Set(db.nodes.map((x) => x.group)).size, ruleCount: db.rules.length
      },
      series
    })
  }],
  ['GET', /^\/dashboard\/realtime$/, () => {
    const s = speed()
    const p = { t: now(), up: s.up, down: s.down }
    series.push(p); if (series.length > 120) series.shift()
    return WRAP({ ...p, cpu: Math.round(s.cpu), mem: Math.round(s.mem), latency: s.latency })
  }],

  // 节点
  ['GET', /^\/node\/list$/, (q) => {
    let rows = [...db.nodes]
    if (q.group) rows = rows.filter((n) => n.group === q.group)
    if (q.status) rows = rows.filter((n) => n.status === q.status)
    if (q.keyword) rows = rows.filter((n) => `${n.name}${n.server}${n.city}${n.country}`.toLowerCase().includes(String(q.keyword).toLowerCase()))
    const sorted = rows.sort((a, b) => (b.current - a.current) || (a.delay ?? 1e9) - (b.delay ?? 1e9)).map(nodeView)
    // groups: 全量分组名(前端筛选器不随分页缺失)
    return WRAP({ ...paginate(sorted, q), groups: [...new Set(db.nodes.map((n) => n.group))] })
  }],
  ['GET', /^\/node\/export$/, () => WRAP(db.nodes.map(({ current, baseDelay, ...n }) => n))],
  ['POST', /^\/node\/import$/, (q, body) => {
    const list = Array.isArray(body?.rows) ? body.rows : []
    let added = 0, skipped = 0
    list.forEach((row) => {
      if (!row?.server || db.nodes.some((n) => n.server === row.server && n.port === row.port)) { skipped++; return }
      db.nodes.push(mkNode(row))
      added++
    })
    pushEvent('sys_op', `批量导入节点：新增 ${added}，跳过 ${skipped}`, { source: '节点管理' })
    return WRAP({ added, skipped })
  }],
  ['POST', /^\/node$/, (q, body) => {
    const n = mkNode(body)
    db.nodes.push(n)
    pushEvent('sys_op', `新增节点 ${n.name}`, { source: '节点管理' })
    return WRAP(n)
  }],
  ['PUT', /^\/node$/, (q, body) => {
    const i = db.nodes.findIndex((n) => n.id === body.id)
    if (i < 0) return FAIL('节点不存在')
    db.nodes[i] = { ...db.nodes[i], ...body }
    return WRAP(db.nodes[i])
  }],
  ['DELETE', /^\/node\/([\d,]+)$/, (q, b, m) => {
    const ids = m[1].split(',').map(Number)
    if (db.nodes.some((n) => ids.includes(n.id) && n.current)) return FAIL('当前使用中的节点不可删除')
    db.nodes = db.nodes.filter((n) => !ids.includes(n.id))
    pushEvent('sys_op', `删除节点 ${ids.length} 个`, { source: '节点管理' })
    return WRAP({ count: ids.length })
  }],
  ['POST', /^\/node\/switch\/(\d+)$/, (q, b, m) => {
    const target = db.nodes.find((n) => n.id === Number(m[1]))
    if (!target) return FAIL('节点不存在')
    const prev = cur()
    if (prev.id === target.id) return FAIL('目标节点已是当前节点')
    prev.current = false
    target.current = true
    target.status = 'switching'
    target.delay = null
    pushEvent('manual_switch', `手动切换 ${prev.name} → ${target.name}`, { from: prev.name, to: target.name, reason: '用户操作' })
    setTimeout(() => { target.status = 'online'; target.delay = target.baseDelay }, 2200)
    return WRAP(nodeView(target))
  }],

  // 规则
  ['GET', /^\/rule\/group$/, () => WRAP(db.groups.map((g) => ({ ...g, ruleCount: db.rules.filter((r) => r.groupId === g.id).length })))],
  ['POST', /^\/rule\/group$/, (q, body) => {
    const g = { id: nextId(), name: body.name }
    db.groups.push(g)
    return WRAP(g)
  }],
  ['DELETE', /^\/rule\/group\/(\d+)$/, (q, b, m) => {
    const id = Number(m[1])
    db.groups = db.groups.filter((g) => g.id !== id)
    db.rules = db.rules.filter((r) => r.groupId !== id)
    return WRAP({ id })
  }],
  ['GET', /^\/rule\/list$/, (q) => {
    const rows = db.rules.filter((r) => !q.groupId || r.groupId === Number(q.groupId))
      .sort((a, b) => a.priority - b.priority)
    return WRAP(rows)
  }],
  ['POST', /^\/rule$/, (q, body) => {
    const { id: _drop, ...rest } = body || {}
    const r = {
      hits: 0, lastHit: null, enabled: true,
      priority: Math.max(0, ...db.rules.map((x) => x.priority)) + 1, ...rest, id: nextId()
    }
    db.rules.push(r)
    return WRAP(r)
  }],
  ['PUT', /^\/rule$/, (q, body) => {
    const i = db.rules.findIndex((r) => r.id === body.id)
    if (i < 0) return FAIL('规则不存在')
    db.rules[i] = { ...db.rules[i], ...body }
    return WRAP(db.rules[i])
  }],
  ['DELETE', /^\/rule\/([\d,]+)$/, (q, b, m) => {
    const ids = m[1].split(',').map(Number)
    db.rules = db.rules.filter((r) => !ids.includes(r.id))
    return WRAP({ count: ids.length })
  }],
  ['PUT', /^\/rule\/reorder$/, (q, body) => {
    (body.ids || []).forEach((id, idx) => {
      const r = db.rules.find((x) => x.id === Number(id))
      if (r) r.priority = idx + 1
    })
    return WRAP(true)
  }],
  ['GET', /^\/rule\/hits$/, (q) => {
    const rule = db.rules.find((r) => r.id === Number(q.ruleId))
    const n = 8
    return WRAP(Array.from({ length: n }, (_, i) => ({
      id: i + 1, time: now() - i * rnd(20_000, 200_000),
      client: `192.168.99.${pick([2, 10, 21, 33, 77])}`,
      query: rule ? (rule.type === 'domain' ? rule.pattern.replace(/^\*/, '') : rule.pattern) : 'example.com',
      action: rule?.action || 'proxy'
    })))
  }],

  // 订阅
  ['GET', /^\/subscription\/list$/, () => WRAP(db.subs)],
  ['POST', /^\/subscription$/, (q, body) => {
    const { id: _drop, ...rest } = body || {}
    const s = { lastFetch: null, autoFetch: true, ...rest, id: nextId() }
    db.subs.push(s)
    return WRAP(s)
  }],
  ['DELETE', /^\/subscription\/(\d+)$/, (q, b, m) => {
    db.subs = db.subs.filter((s) => s.id !== Number(m[1]))
    return WRAP(true)
  }],
  ['POST', /^\/subscription\/fetch\/(\d+)$/, (q, b, m) => {
    const s = db.subs.find((x) => x.id === Number(m[1]))
    if (!s) return FAIL('订阅不存在')
    if (Math.random() < 0.25) {
      pushEvent('sub_fail', `订阅「${s.name}」拉取失败`, { reason: '上游返回 502', source: '订阅' })
      return FAIL('订阅源不可达，已保留现有节点')
    }
    const add = Array.from({ length: 3 }, () => {
      const [city, country, flag, group, baseDelay, server] = pick(NODE_SEED)
      const n = {
        id: nextId(), name: `${flag} ${city} 新增${String(seq).slice(-2)}`, server, port: pick([51820, 443, 8443]),
        group, country, city, flag, status: 'online', baseDelay, delay: baseDelay, loss: 0,
        upBytes: 0, downBytes: 0, lastCheck: now(), current: false
      }
      db.nodes.push(n)
      return n
    })
    s.lastFetch = now()
    pushEvent('sub_fetch', `订阅「${s.name}」拉取成功，新增 ${add.length} 个节点`, { source: '订阅' })
    return WRAP({ added: add.length, nodes: add.map((x) => x.name) })
  }],

  // 事件
  ['GET', /^\/event\/list$/, (q) => {
    let rows = [...db.events]
    if (q.type) {
      const types = String(q.type).split(',').filter(Boolean)
      rows = rows.filter((e) => types.includes(e.type))
    }
    if (q.keyword) rows = rows.filter((e) => e.message.includes(q.keyword) || (e.detail || '').includes(q.keyword))
    return WRAP(paginate(rows, q))
  }],
  ['DELETE', /^\/event$/, () => { db.events = []; return WRAP(true) }],

  // 系统
  ['GET', /^\/system\/info$/, () => WRAP({
    hostname: 'route-gw (LXC 201)', os: 'Ubuntu 24.04.1 LTS', kernel: '6.8.0-41-generic',
    cpu: '1 vCore / 负载 0.12', memUsed: '212 MB', memTotal: '512 MB',
    uptime: `${Math.floor((now() - (bootAt * 1000)) / 3600_000)} 小时`, loadAvg: '0.12 0.09 0.06',
    gatewayIp: '192.168.99.1 (eth1) / <GW_IP> (eth0)', dnsMode: 'dnsmasq 分流 (53)',
    listUpdatedAt: now() - 3600_000 * 7, bootAt: bootAt * 1000, bootAtText: new Date(bootAt * 1000).toISOString()
  })],
  ['GET', /^\/system\/tunnel$/, () => {
    const n = cur()
    return WRAP({
      wgUp: n.status !== 'offline', listen: 51608,
      peer: { pubkey: '<peer-pubkey>', endpoint: `${n.server}:${n.port}`,
              allowed: '0.0.0.0/1,128.0.0.0/1', handshake: Math.floor((now() - 42_000) / 1000),
              rx: n.downBytes, tx: n.upBytes, keepalive: 25 },
      rules: [{ from: 'all', table: 'main', priority: 32764 }, { from: 'all', table: '51820', priority: 32765 }],
      mainRoutes: db.config.chinaRouteCount, tableRoutes: 1,
      latency: n.delay, loss: n.loss, exitIp: EXIT_IPS[0],
      queryLog: true, hitsTracked: db.rules.reduce((s, r) => s + (r.hits || 0), 0),
      autoswitch: db.autoSwitch, lastSwitch: Math.floor((now() - 3600_000 * 3) / 1000)
    })
  }],
  ['POST', /^\/system\/reload$/, () => {
    pushEvent('sys_op', '重载分流配置：规则 ' + db.rules.length + ' 条 / 域名 4372 条', { source: '系统' })
    return WRAP(true)
  }],
  ['POST', /^\/system\/restart$/, () => {
    const n = cur()
    n.status = 'switching'; n.delay = null
    setTimeout(() => { n.status = 'online'; n.delay = n.baseDelay }, 3000)
    pushEvent('sys_op', '网关重启：wg0 隧道重建，中断 2.8s', { source: '系统' })
    return WRAP(true)
  }],
  ['GET', /^\/system\/backup$/, () => WRAP({
    version: 1, exportedAt: now(),
    nodes: db.nodes.map(({ current, baseDelay, ...n }) => n),
    groups: db.groups, rules: db.rules, subs: db.subs.map(({ url, ...s }) => ({ ...s, url })),
    autoSwitch: db.autoSwitch, config: db.config
  })],
  ['POST', /^\/system\/restore$/, (q, body) => {
    if (!body || typeof body !== 'object') return FAIL('备份文件格式不正确')
    if (body.nodes) db.nodes = body.nodes.map((n) => ({ ...n, status: 'offline', delay: null, current: n.current ?? false }))
    if (body.groups) db.groups = body.groups
    if (body.rules) db.rules = body.rules
    if (body.subs) db.subs = body.subs
    if (body.autoSwitch) db.autoSwitch = body.autoSwitch
    if (body.config) db.config = body.config
    const first = db.nodes.find((n) => n.current) || db.nodes[0]
    if (first) { first.current = true; first.status = 'online'; first.delay = first.baseDelay || first.delay || 80 }
    pushEvent('sys_op', `恢复备份：节点 ${db.nodes.length} / 规则 ${db.rules.length}`, { source: '系统' })
    return WRAP(true)
  }],
  ['GET', /^\/system\/config$/, () => WRAP(db.config)],
  ['PUT', /^\/system\/config$/, (q, body) => {
    Object.assign(db.config, body || {})
    pushEvent('sys_op', '更新网关基础配置', { source: '系统', detail: JSON.stringify(body, null, 2) })
    return WRAP(db.config)
  }],
  ['GET', /^\/system\/autoswitch$/, () => WRAP(db.autoSwitch)],
  ['PUT', /^\/system\/autoswitch$/, (q, body) => {
    Object.assign(db.autoSwitch, body || {})
    pushEvent('sys_op', `自动切换策略已更新（${db.autoSwitch.enabled ? '启用' : '停用'}，冷却 ${db.autoSwitch.cooldown}s）`, { source: '系统' })
    return WRAP(db.autoSwitch)
  }],
  ['POST', /^\/system\/probe-now$/, () => {
    db.nodes.forEach((n) => {
      if (n.status === 'switching') return
      n.status = Math.random() < 0.9 ? 'online' : 'fault'
      n.delay = n.status === 'online' ? n.baseDelay + Math.round(rnd(-10, 20)) : null
      n.loss = n.status === 'online' ? Math.round(rnd(0, 15)) / 100 : 1
      n.lastCheck = now()
    })
    const online = db.nodes.filter((n) => n.status === 'online').length
    pushEvent('sys_op', `手动全量探测完成：${online}/${db.nodes.length} 在线`, { source: '探测' })
    return WRAP({ online, total: db.nodes.length })
  }]
]
const bootAt = Math.floor(Date.now() / 1000) - 3600 * 26

// ---------------- HTTP ----------------
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1')
  if (!url.pathname.startsWith('/api')) {
    res.writeHead(404, { 'content-type': 'application/json' })
    return res.end(JSON.stringify(FAIL('接口不存在')))
  }
  const path = url.pathname.replace(/^\/api/, '') || '/'
  const q = Object.fromEntries(url.searchParams.entries())

  const readBody = () => new Promise((resolve) => {
    let raw = ''
    req.on('data', (c) => { raw += c })
    req.on('end', () => { try { resolve(raw ? JSON.parse(raw) : {}) } catch { resolve({}) } })
  })

  readBody().then((body) => {
    const hit = routes.find(([method, re]) => method === req.method && re.test(path))
    let out
    let headers = { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' }
    if (!hit) out = FAIL(`Mock 未实现: ${req.method} ${path}`, 404)
    else if (!isAuthed(req) && !PUBLIC_API.some((re) => re.test(path))) out = FAIL('未登录', 401)
    else {
      const m = path.match(hit[1])
      try { out = hit[2](q, body, m, req) } catch (e) { out = FAIL(e.message) }
      if (path === '/login' && out.code === 200) {
        headers['set-cookie'] = `${AUTH.cookie}=${AUTH.sid}; Path=/; SameSite=Lax`
      }
      if (path === '/logout') headers['set-cookie'] = `${AUTH.cookie}=; Path=/; Max-Age=0`
    }
    // 命中计数模拟
    if (req.method === 'GET' && path === '/dashboard/realtime') {
      db.rules.forEach((r) => {
        if (r.enabled && Math.random() < 0.5) { r.hits = (r.hits || 0) + Math.round(rnd(1, 4)); r.lastHit = now() }
      })
    }
    res.writeHead(200, headers)
    res.end(JSON.stringify(out))
  })
})
server.on('error', (e) => {
  if (e.code === 'EADDRINUSE') console.log(`[mock] 端口 ${PORT} 已被占用，视为已有 Mock 实例在运行，本进程不再监听。`)
  else console.log('[mock] 启动失败:', e.message)
})
server.listen(PORT, '127.0.0.1', () => {
  console.log(`[mock] 分流网关假数据服务已启动 → http://127.0.0.1:${PORT}/api  (节点 ${db.nodes.length} / 规则 ${db.rules.length})`)
})
