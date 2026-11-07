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
  ['洛杉矶', '美国', '🇺🇸', 'HK-优化', 142, 'us-lax-01.example.com'],
  ['圣何塞', '美国', '🇺🇸', 'HK-优化', 158, 'us-sjc-02.example.com'],
  ['纽约', '美国', '🇺🇸', 'US-原生', 96, 'us-nyc-03.example.com'],
  ['东京', '日本', '🇯🇵', 'HK-优化', 78, 'jp-tyo-01.example.com'],
  ['大阪', '日本', '🇯🇵', 'JP-原生', 85, 'jp-osa-02.example.com'],
  ['香港', '中国香港', '🇭🇰', 'HK-优化', 42, 'hk-hkg-01.example.com'],
  ['九龙', '中国香港', '🇭🇰', 'HK-优化', 55, 'hk-kln-02.example.com'],
  ['台北', '中国台湾', '🇹🇼', 'HK-优化', 68, 'tw-tpe-01.example.com'],
  ['新加坡', '新加坡', '🇸🇬', 'HK-优化', 88, 'sg-sin-01.example.com'],
  ['首尔', '韩国', '🇰🇷', 'KR-原生', 92, 'kr-sel-01.example.com'],
  ['法兰克福', '德国', '🇩🇪', 'EU-原生', 232, 'de-fra-01.example.com'],
  ['伦敦', '英国', '🇬🇧', 'EU-原生', 248, 'uk-lon-01.example.com'],
  ['阿姆斯特丹', '荷兰', '🇳🇱', 'NL-原生', 214, 'nl-ams-02.example.com'],
  ['温哥华', '加拿大', '🇨🇦', 'US-原生', 168, 'ca-yvr-01.example.com'],
  ['悉尼', '澳大利亚', '🇦🇺', 'AU-原生', 176, 'au-syd-01.example.com']
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
    { id: 1, name: '机场主订阅', url: 'https://matrix.example.com:3333/sub/aaaa', autoFetch: true, lastFetch: now() - 3600_000 * 5 },
    { id: 2, name: '备用订阅', url: 'https://matrix.example.com:3333/sub/bbbb', autoFetch: false, lastFetch: now() - 86400_000 * 2 }
  ],
  events: [],
  config: {
    wanIf: 'enp3s0', wanGw: '192.168.0.1', lanIf: 'enp3s0', lanIp: '192.168.0.125',
    lanPrefix: 24, lanCidr: '192.168.0.0/24', dnsAddr: '192.168.0.125', wgLan: '10.14.0.2/16',
    mssClamp: true, listUpdateAt: '04:30', chinaRouteCount: 7461, gfwDomainCount: 4372
  },
  autoSwitch: {
    enabled: true, probeType: 'ping', interval: 30, timeout: 3, failThreshold: 3,
    cooldown: 300, sameRegionFirst: true, groups: ['HK-优化', 'US-原生'], resetDay: 1
  }
}

// ---------------- 事件流 ----------------
function pushEvent(type, message, extra = {}) {
  const { ago = 0, ...rest } = extra      // ago(秒)：回填演示事件的时间，让切换的"发起/结果"能配出耗时
  db.events.unshift({
    id: nextId(), time: now() - ago * 1000, type, message,
    source: rest.source || '自动自愈', from: rest.from, to: rest.to,
    reason: rest.reason, latency: rest.latency ?? null, loss: rest.loss ?? null,
    detail: rest.detail || JSON.stringify(rest, null, 2)
  })
  if (db.events.length > 300) db.events.length = 300
}
pushEvent('sys_op', '网关服务启动，加载策略路由 3 条 / 国内明细 7461 条', { source: '系统', ago: 7260 })
pushEvent('manual_switch', `手动切换到 🇭🇰 香港 01`, { from: '🇹🇼 台北 01', to: '🇭🇰 香港 01', reason: '用户操作', ago: 7200 })
pushEvent('node_up', '🇭🇰 香港 01 握手完成，隧道可用', { to: '🇭🇰 香港 01', ago: 7196, latency: 71 })
pushEvent('auto_switch', '🇯🇵 东京 01 连续 3 次探测失败，已切换至 🇭🇰 九龙 02', { from: '🇯🇵 东京 01', to: '🇭🇰 九龙 02', reason: 'TCPing 超时 (丢包 100%)', ago: 6300 })
pushEvent('node_down', '🇭🇰 九龙 02 握手超时，已回滚到 🇯🇵 东京 01', { to: '🇭🇰 九龙 02', ago: 6292 })
pushEvent('sub_fetch', '订阅「机场主订阅」拉取成功，新增 3 个节点', { source: '订阅', ago: 6000 })
pushEvent('node_down', '🇩🇪 法兰克福 01 离线', { reason: '握手超时', ago: 5800 })

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
  // 切换的结果事件(握手完成)稍后落地，让「切换历史」页能配出耗时与结论
  setTimeout(() => pushEvent('node_up', `${target.name} 握手完成，隧道可用`, { from: bad.name, to: target.name, latency: target.delay, loss: target.loss }), 3200)
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
// 出口 IP 用 RFC 5737 文档保留段(203.0.113.0/24)，不要填真实节点地址
const EXIT_IPS = ['203.0.113.46', '203.0.113.107', '203.0.113.30']
function nodeView(n) {
  return { ...n, exitIp: n.current ? EXIT_IPS[0] : undefined }
}

// ---------------- 观测类假数据(DNS / 终端 / 日志 / 数据源) ----------------
const fv = (path, label, o = {}) => ({
  path, label, exists: o.exists ?? true, bytes: o.bytes ?? 0, counted: true,
  lines: o.lines ?? 0, serverLines: o.serverLines ?? 0, addressLines: o.addressLines ?? 0,
  mtime: o.mtime ?? (now() - 3600_000 * 6)
})
const APP_MATRIX = 'https://matrix.example.com:3333'
const DNS_VIEWS = [
  { key: 'local', label: '本机 dnsmasq(分流结果)', server: '127.0.0.1' },
  { key: 'proxy', label: '隧道上游', server: '198.51.100.53' },
  { key: 'direct', label: '直连上游', server: '203.0.113.53' }
]
// 假解析结果用文档保留网段，避免和真实地址撞车
const fakeIp = (name, salt) => {
  let h = 7
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) % 200
  return `198.51.100.${(h + salt) % 200 + 20}`
}
const fakeIpv6 = (name, salt) => {
  let h = 11
  for (const ch of name) h = (h * 17 + ch.charCodeAt(0)) % 60000
  return `2001:db8::${(h + salt).toString(16)}`
}
const dnsQuery = (view, name, qtype) => ({
  server: view.server, qtype, ok: true,
  ips: qtype === 'AAAA'
    ? [fakeIpv6(name, view.key === 'local' ? 0 : 7)]
    : [fakeIp(name, view.key === 'local' ? 0 : 7)],
  cname: name.startsWith('www.') ? name.replace('www.', 'a.') : '',
  rcode: 'NOERROR', truncated: false, ms: Math.round(rnd(4, view.key === 'proxy' ? 180 : 40)), error: ''
})
const dnsMatched = (name) => db.rules.filter((r) => r.enabled && r.type === 'domain'
  && (r.pattern === name || (r.pattern.startsWith('*.') && name.endsWith(r.pattern.slice(1)))))
// 命中流水与设备表：每次读取时按当前规则滚动生成，模拟持续有查询进来
let hitSeq = 0
function rollHits(n) {
  const rules = db.rules.filter((r) => r.enabled && r.type === 'domain')
  const out = []
  for (let i = 0; i < n; i++) {
    // 与生产一致：只有命中规则的查询才进流水
    const hit = pick(rules)
    out.push({ id: ++hitSeq, time: now() - i * 1200, client: `192.168.99.${10 + (i % 4)}`,
               query: (hit.pattern || '').replace(/^\*\./, ''), action: hit.action, ruleId: hit.id })
  }
  return out
}
const CLIENT_SEED = [
  { ip: '192.168.99.10', mac: 'a4:5e:60:c1:02:0a', hostname: 'laptop-z', dev: 'eth1', neighState: 'REACHABLE' },
  { ip: '192.168.99.22', mac: '3c:06:30:7f:a1:22', hostname: 'phone-a', dev: 'eth1', neighState: 'STALE' },
  { ip: '192.168.99.31', mac: 'f0:9f:3d:11:be:31', hostname: 'tv-box', dev: 'eth1', neighState: 'DELAY' },
  { ip: '192.168.99.44', mac: 'ac:84:c6:02:9f:44', hostname: 'nas-01', dev: 'eth1', neighState: 'REACHABLE' },
  { ip: '192.168.99.55', mac: '88:a9:c7:55:1d:55', hostname: '', dev: 'eth1', neighState: 'PROBE' }
]
function clientRows() {
  return CLIENT_SEED.map((c, i) => {
    const queries = 40 + i * 17 + (tick * 3 % 40)
    const proxy = Math.round(queries * (0.2 + i * 0.07))
    const last = now() - i * 9000
    return {
      ip: c.ip, dev: c.dev, mac: c.mac, neighState: c.neighState, hostname: c.hostname,
      leaseExpires: last + 3600_000 * 6, queries, proxy, direct: queries - proxy, reject: i === 3 ? 2 : 0,
      types: { A: Math.round(queries * 0.7), AAAA: Math.round(queries * 0.3) },
      recent: ['github.com', 'openai.com', 'baidu.com', 'youtube.com'].slice(0, 2 + (i % 3)),
      lastQuery: last, firstSeen: bootAt * 1000 + i * 60_000, idle: Math.round((now() - last) / 1000),
      active: i < 3
    }
  })
}
// 延迟序列只在"真实 ping 点"上出样(15s 一次)，与生产 GW.remeasure 节奏一致
const latencySeries = Array.from({ length: 60 }, (_, i) => {
  const bad = i === 41 || i === 42
  return { t: now() - (60 - i) * 15_000, ms: bad ? null : Math.round((baseOf(cur()) + rnd(-14, 22)) * 10) / 10,
           loss: bad ? 0.25 : Math.random() < 0.06 ? 0.05 : 0 }
})
// 切换历史要"发起 → 结果"成对才好看，演示数据在此补齐几组(时间倒序后由 unshift 维护)
;[
  { type: 'manual_switch', msg: '手动切换到 🇯🇵 东京 01', from: '🇹🇼 台北 01', to: '🇯🇵 东京 01', reason: '用户操作', ago: 5400 },
  { type: 'node_up', msg: '🇯🇵 东京 01 握手完成，隧道可用', from: '🇹🇼 台北 01', to: '🇯🇵 东京 01', ago: 5396, latency: 78, lossPct: 0 },
  { type: 'auto_switch', msg: '🇰🇷 首尔 01 连续 3 次探测失败，已切换至 🇭🇰 香港 01', from: '🇰🇷 首尔 01', to: '🇭🇰 香港 01', reason: 'ICMP 超时(丢包 100%)', ago: 3000 },
  { type: 'node_down', msg: '🇭🇰 香港 01 握手超时，已回滚到 🇰🇷 首尔 01', from: '🇰🇷 首尔 01', to: '🇭🇰 香港 01', ago: 2992 },
  { type: 'auto_switch', msg: '🇭🇰 香港 01 故障，自动切换至 🇹🇼 台北 01', from: '🇭🇰 香港 01', to: '🇹🇼 台北 01', reason: '同区域优先命中', ago: 1200 },
  { type: 'self_heal', msg: '🇹🇼 台北 01 自愈成功，延迟回落', from: '🇭🇰 香港 01', to: '🇹🇼 台北 01', ago: 1194, latency: 68, lossPct: 0 }
].forEach((e) => db.events.unshift({
  id: nextId(), time: now() - e.ago * 1000, type: e.type, message: e.msg,
  source: e.type === 'manual_switch' ? '面板' : '自动自愈',
  from: e.from, to: e.to, reason: e.reason || '', detail: '', latency: e.latency, loss: (e.lossPct || 0) / 100
}))
db.events.sort((a, b) => b.time - a.time)
const LOG_LINES = {
  dnsmasq: (i) => ['dnsmasq[612]: query[A] github.com from 192.168.99.10',
    'dnsmasq[612]: forwarded github.com to 198.51.100.53',
    'dnsmasq[612]: reply github.com is 198.51.100.66',
    'dnsmasq[612]: query[A] baidu.com from 192.168.99.22',
    'dnsmasq[612]: cached baidu.com is 203.0.113.30'][i % 5],
  wireguard: (i) => ['wg-quick@wg0.service: Setting wg0 as a default route is disabled',
    'wg-quick@wg0.service: adding route 0.0.0.0/1 dev wg0',
    'wireguard: wg0: Received packet from 198.51.100.20:51820',
    'wireguard: wg0: Sending keepalive message',
    'wireguard: wg0: Peer 10.14.0.2 has been removed'][i % 5],
  panel: (i) => ['gw-admin[700]: 面板监听 127.0.0.1:8080', 'gw-admin[700]: 健康线程: 当前隧道可用',
    'gw-admin[700]: 探测批次 40 个节点完成', 'gw-admin[700]: 矩阵同步: 43 个节点写回',
    'gw-admin[700]: 延迟实测 118.4ms loss=0'][i % 5],
  lists: (i) => ['[route-update] 下载国内 IP 明细…', '[route-update] 生成策略路由 7481 条',
    '[route-update] 下载 gfwlist…', '[route-update] 写入分流域名 4372 条',
    '[route-update] 重载 dnsmasq 完成'][i % 5]
}
const logTs = (back) => new Date(now() - back * 1000).toISOString().replace('T', ' ').slice(0, 19)

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
    return WRAP({ ...paginate(sorted, q), groups: [...new Set(db.nodes.map((n) => n.group))], nodeSource: APP_MATRIX })
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
    setTimeout(() => {
      target.status = 'online'
      target.delay = target.baseDelay
      pushEvent('node_up', `${target.name} 握手完成，隧道可用`, { from: prev.name, to: target.name, latency: target.delay, loss: target.loss })
    }, 2200)
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
    hostname: 'route-gw (旁路由)', mode: 'same-subnet-bypass',
    lanIf: 'enp3s0', lanIp: '192.168.0.125', lanPrefix: 24, lanCidr: '192.168.0.0/24', dnsAddr: '192.168.0.125',
    os: 'Ubuntu 24.04.1 LTS', kernel: '6.8.0-41-generic',
    cpu: '1 vCore / 负载 0.12', memUsed: '212 MB', memTotal: '512 MB',
    uptime: `${Math.floor((now() - (bootAt * 1000)) / 3600_000)} 小时`, loadAvg: '0.12 0.09 0.06',
    gatewayIp: '192.168.0.125 (enp3s0)', dnsMode: 'dnsmasq 分流 (53)',
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
  }],

  // ---- 延迟历史(仪表盘曲线) ----
  ['GET', /^\/dashboard\/latency$/, () => {
    const vals = latencySeries.map((s) => s.ms).filter((v) => v != null)
    return WRAP({
      series: latencySeries, current: cur().delay, loss: cur().loss,
      target: '223.5.5.5', every: 15, measuredAt: now(),
      stats: { samples: vals.length, min: Math.min(...vals), max: Math.max(...vals),
               avg: Math.round(vals.reduce((a, b) => a + b, 0) / vals.length * 10) / 10,
               lossSamples: latencySeries.filter((s) => s.loss).length,
               windowSec: latencySeries.length * 15 }
    })
  }],

  // ---- DNS 管理 ----
  ['GET', /^\/dns\/overview$/, () => {
    const files = [
      fv('/etc/dnsmasq.d/97-panel.conf', '面板下发(分流规则页)', { lines: 26, serverLines: 18, addressLines: 4 }),
      fv('/etc/dnsmasq.d/98-custom-domain.conf', '手工补充域名(不被 cron 覆盖)', { lines: 6, serverLines: 6 }),
      fv('/etc/dnsmasq.d/99-gfw.conf', 'gfwlist 生成(cron 每日更新)', { lines: 4372, serverLines: 4372, bytes: 186_512 })
    ]
    return WRAP({
      views: DNS_VIEWS,
      listPath: '/etc/china_ip_list.txt',
      service: { active: 'active', enabled: 'enabled', listening: true, version: 'Dnsmasq version 2.90' },
      queryLog: true, baseUpstreams: ['223.5.5.5', '114.114.114.114'],
      proxyUpstream: '198.51.100.53', directUpstream: '203.0.113.53', local: '127.0.0.1:53',
      counts: { chinaIp: 7481, gfwDomain: 4372, panelDomain: 22, customDomain: 6,
                ruleDomain: db.rules.filter((r) => r.type === 'domain' && r.enabled).length,
                ruleIp: db.rules.filter((r) => r.type !== 'domain' && r.enabled).length },
      files, observed: { hitsTracked: 400, clients: CLIENT_SEED.length }
    })
  }],
  ['GET', /^\/dns\/query$/, (q) => {
    const name = String(q.domain || '').trim().replace(/\.$/, '')
    if (!name || !/^[A-Za-z0-9._\-*]{1,253}$/.test(name)) return FAIL('域名格式不正确')
    const qtype = (q.type || 'A').toUpperCase()
    if (!['A', 'AAAA'].includes(qtype)) return FAIL('只支持 A / AAAA 查询')
    const rows = DNS_VIEWS.filter((v) => !q.view || q.view === 'all' || v.key === q.view)
      .map((v) => ({ ...dnsQuery(v, name, qtype), key: v.key, label: v.label }))
    return WRAP({ domain: name, type: qtype, results: rows, matches: dnsMatched(name) })
  }],
  ['GET', /^\/dns\/hits$/, (q) => {
    const n = Math.max(1, Math.min(400, Number(q.limit) || 80))
    return WRAP({ rows: rollHits(n), clients: CLIENT_SEED.length, tracked: 400 })
  }],

  // ---- 终端设备 ----
  ['GET', /^\/client\/list$/, (q) => {
    let rows = clientRows()
    if (q.active) rows = rows.filter((r) => r.active)
    if (q.keyword) {
      const kw = String(q.keyword).toLowerCase()
      rows = rows.filter((r) => `${r.ip} ${r.mac} ${r.hostname} ${r.recent.join(' ')}`.toLowerCase().includes(kw))
    }
    rows = rows.sort((a, b) => b.queries - a.queries)
    return WRAP({ ...paginate(rows, q),
      stat: { total: rows.length, active: rows.filter((r) => r.active).length, activeWindow: 180,
              neigh: rows.length,
              leases: rows.length, quiet: rows.filter((r) => !r.queries).length,
              proxyTotal: rows.reduce((s, r) => s + r.proxy, 0), directTotal: rows.reduce((s, r) => s + r.direct, 0) } })
  }],

  // ---- 切换历史(把事件流的"发起 → 结果"配对) ----
  ['GET', /^\/switch\/history$/, (q) => {
    const pending = {}, rows = [], done = {}
    const mk = (a, o) => ({
      id: (a || o).id, at: (a || o).time,
      trigger: a ? (a.type === 'manual_switch' ? '手动' : '自动自愈') : '隧道事件',
      from: (a || o).from ?? null, to: (a || o).to ?? null,
      reason: (a || o).reason || o?.reason || '',
      result: !o ? 'pending' : o.type === 'node_up' ? 'success'
        : (o.message || '').includes('回滚') ? 'rollback' : (o.message || '').includes('成功') ? 'success' : 'fail',
      cost: o ? Math.round((o.time - (a || o).time) / 100) / 10 : null,
      latency: o?.latency ?? null, loss: o?.loss ?? 0,
      attemptMsg: a?.message || '', outcomeMsg: o?.message || ''
    })
    ;[...db.events].reverse().forEach((e) => {
      if (!['manual_switch', 'auto_switch', 'node_up', 'node_down', 'self_heal'].includes(e.type)) return
      // 与生产一致：不带 to 的 node_down/node_up 只是探测判故障，不算一次切换
      if (!e.to && e.type !== 'self_heal') return
      if (e.type === 'manual_switch' || e.type === 'auto_switch') {
        if (!e.to) { rows.push(mk(e, null)); return }
        if (pending[e.to]) rows.push(mk(pending[e.to], null))
        pending[e.to] = e
      } else if (e.to && pending[e.to]) { rows.push(mk(pending[e.to], e)); delete pending[e.to]; done[e.to] = e.time }
      else if (e.to && e.type === 'self_heal' && (done[e.to] || 0) >= e.time - 60000) { /* 同一次切换的汇总事件，不重复成行 */ }
      else rows.push(mk(null, e))
    })
    rows.push(...Object.values(pending).map((e) => mk(e, null)))
    let out = rows.sort((a, b) => b.at - a.at)
    if (q.result) out = out.filter((r) => r.result === q.result)
    if (q.keyword) {
      const kw = String(q.keyword).toLowerCase()
      out = out.filter((r) => `${r.from} ${r.to} ${r.reason} ${r.attemptMsg} ${r.outcomeMsg}`.toLowerCase().includes(kw))
    }
    const costs = out.map((r) => r.cost).filter((c) => c != null)
    return WRAP({
      ...paginate(out, q),
      summary: { total: out.length, success: out.filter((r) => r.result === 'success').length,
                 fail: out.filter((r) => ['fail', 'rollback'].includes(r.result)).length,
                 pending: out.filter((r) => r.result === 'pending').length,
                 avgCost: costs.length ? Math.round(costs.reduce((a, b) => a + b, 0) / costs.length * 10) / 10 : null },
      current: cur().name, lastSwitchAt: now() - 3600_000 * 3, autoswitch: db.autoSwitch
    })
  }],

  // ---- 日志查看器(白名单源) ----
  ['GET', /^\/system\/log-units$/, () => WRAP([
    { key: 'dnsmasq', label: 'DNS 解析(dnsmasq)', kind: 'journal', unit: 'dnsmasq.service', active: 'active', enabled: 'enabled' },
    { key: 'wireguard', label: '隧道(wg-quick)', kind: 'journal', unit: 'wg-quick@wg0.service', active: 'active', enabled: 'enabled' },
    { key: 'panel', label: '面板(gw-admin)', kind: 'journal', unit: 'gw-admin.service', active: 'active', enabled: 'enabled' },
    { key: 'lists', label: '数据源更新日志', kind: 'file', file: fv('/var/log/update-lists.log', '数据源更新日志', { lines: 412 }), active: 'active', enabled: '-' }
  ])],
  ['GET', /^\/system\/logs$/, (q) => {
    const key = q.unit || 'dnsmasq'
    if (!LOG_LINES[key]) return FAIL(`日志源不在白名单内: ${key}`)
    const want = Math.max(20, Math.min(400, Number(q.lines) || 200))
    const kw = String(q.keyword || '').toLowerCase()
    const isFile = key === 'lists'      // 与生产一致：journal 源时间戳单独给 t/head，文件源时间戳留在正文
    const all = Array.from({ length: Math.min(want * 3, 120) }, (_, i) => ({
      t: isFile ? null : now() - i * 4000,
      head: isFile ? '' : logTs(i * 4),
      text: isFile ? `${logTs(i * 4)} ${LOG_LINES[key](i)}` : LOG_LINES[key](i)
    }))
    const hit = all.filter((l) => !kw || l.text.toLowerCase().includes(kw))
    return WRAP({ unit: key, label: key, source: key === 'lists' ? '/var/log/update-lists.log' : `${key}.service`,
                  lines: hit.slice(0, want), requested: want, matched: hit.length, scanned: all.length })
  }],

  // ---- 分流数据源 ----
  ['GET', /^\/list\/status$/, () => {
    const next = new Date()
    next.setHours(4, 30, 0, 0)
    if (next.getTime() < now()) next.setDate(next.getDate() + 1)
    return WRAP({
      counts: { chinaIp: 7481, gfwDomain: 4372 },
      files: [
        fv('/etc/china_ip_list.txt', '国内 IP 明细表(策略路由用)', { lines: 7481, bytes: 289_412 }),
        fv('/etc/dnsmasq.d/99-gfw.conf', 'gfwlist 域名(dnsmasq 分流)', { lines: 4372, serverLines: 4372, bytes: 186_512 }),
        fv('/etc/dnsmasq.d/98-custom-domain.conf', '手工补充域名', { lines: 6, serverLines: 6 }),
        fv('/etc/dnsmasq.d/97-panel.conf', '面板下发域名', { lines: 26, serverLines: 18, addressLines: 4 }),
        fv('/usr/local/bin/update-lists.sh', '更新脚本', { lines: 58 }),
        fv('/etc/cron.d/route-lists', '定时任务', { lines: 2 }),
        fv('/var/log/update-lists.log', '更新日志', { lines: 412, bytes: 51_213 })
      ],
      cronAt: '04:30', cronNext: next.getTime(), scriptOk: true,
      logTail: [0, 1, 2, 3, 4].map((i) => `${logTs(i * 200)} ${LOG_LINES.lists(i)}`),
      matrix: { url: APP_MATRIX, total: db.nodes.length, updatedAt: now() - 3600_000 * 5,
                builtAt: '2026-10-30 04:31:00', fetchInterval: 21600 },
      subs: db.subs.map((s) => ({ ...s, nodeCount: s.id === 1 ? db.nodes.length : 6 }))
    })
  }],
  ['POST', /^\/list\/update$/, () => {
    pushEvent('sys_op', '手动更新分流数据源：国内 IP 7481 条 / 分流域名 4372 条(成功)', { source: '数据源' })
    return WRAP({ rc: 0, china: 7481, gfw: 4372, log: [0, 1, 2, 3].map((i) => LOG_LINES.lists(i)) },
                '数据源更新完成')
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
