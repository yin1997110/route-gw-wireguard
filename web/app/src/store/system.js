// 职责: 系统域状态——仪表盘实时时序(轮询)、事件日志、系统操作、自动切换配置。
// EXTENSION_POINT: realtime 轮询可平滑替换为 WebSocket/SSE，仅需改本文件 start/stop。
import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import * as dashApi from '@/api/dashboard'
import * as eventApi from '@/api/event'
import * as sysApi from '@/api/system'
import { REFRESH, PAGINATION } from '@/constants/config'

export const useSystemStore = defineStore('system', () => {
  // ---- 仪表盘 ----
  const overview = ref(null)          // 静态概览: 节点信息/今日本月/运行时长
  const points = ref([])              // 时序 ring buffer [{t,up,down}]
  const live = reactive({ up: 0, down: 0, cpu: 0, mem: 0, latency: 0 })
  let timer = null

  async function fetchOverview() {
    const data = await dashApi.getOverview()
    overview.value = data.node
    Object.assign(overviewMeta, data.meta)
    // 曲线缓冲以实时采样为准，overview 的 series 只在首次(缓冲为空)时铺底
    if (!points.value.length) points.value = data.series
  }
  const overviewMeta = reactive({})   // todayUp/todayDown/monthUp... 平铺

  // 隧道延迟历史：后端只在"真的 ping 过"的点上出样，这里整段取回，不拿 2s 轮询插值
  const latencyPoints = ref([])
  const latencyStats = ref({})
  const latencyHead = ref({})
  async function fetchLatency() {
    try {
      const d = await dashApi.getLatency()
      latencyPoints.value = d.series
      latencyStats.value = d.stats
      latencyHead.value = { current: d.current, loss: d.loss, target: d.target, every: d.every, measuredAt: d.measuredAt }
    } catch { /* 曲线取不到不打断仪表盘其余部分 */ }
  }

  function startRealtime() {
    stopRealtime()
    poll()
    timer = setInterval(poll, REFRESH.REALTIME_INTERVAL * 1000)
  }
  function stopRealtime() { if (timer) { clearInterval(timer); timer = null } }
  let ticks = 0
  async function poll() {
    try {
      const d = await dashApi.getRealtime()
      Object.assign(live, { up: d.up, down: d.down, cpu: d.cpu, mem: d.mem, latency: d.latency })
      points.value.push({ t: d.t, up: d.up, down: d.down })
      if (points.value.length > REFRESH.CHART_WINDOW) points.value.shift()
      // 概览(当前节点/流量/运行时长)随轮询低频刷新，避免节点卡片停在入场那一刻
      if (++ticks % REFRESH.OVERVIEW_EVERY === 0) {
        await fetchOverview()
        fetchLatency()
      }
    } catch { /* 轮询失败静默，等待下轮 */ }
  }

  // ---- 事件日志 ----
  const events = ref([])
  const eventTotal = ref(0)
  const eventLoading = ref(false)
  const eventQuery = reactive({ pageNum: 1, pageSize: PAGINATION.PAGE_SIZE, type: '', keyword: '' })
  async function fetchEvents() {
    eventLoading.value = true
    try {
      const d = await eventApi.listEvent(eventQuery)
      events.value = d.rows
      eventTotal.value = d.total
    } finally { eventLoading.value = false }
  }
  async function clearEvents() {
    await eventApi.clearEvent()
    ElMessage.success('日志已清空')
    await fetchEvents()
  }

  // ---- 系统 ----
  const sysInfo = ref(null)
  async function fetchSysInfo() { sysInfo.value = await sysApi.getSysInfo() }
  async function reload() { await sysApi.reloadGw(); ElMessage.success('配置已重载') }
  async function restart() { await sysApi.restartGw(); ElMessage.success('网关重启指令已下发') }
  async function backup() { return sysApi.getBackup() }
  async function restore(data) { await sysApi.restoreBackup(data); ElMessage.success('备份已恢复') }

  const autoSwitch = ref(null)
  async function fetchAutoSwitch() { autoSwitch.value = await sysApi.getAutoSwitch() }
  async function saveAutoSwitch(form) {
    autoSwitch.value = await sysApi.putAutoSwitch(form)
    ElMessage.success('已保存并在网关生效')
  }
  async function probeNow() {
    const r = await sysApi.probeNow()
    ElMessage.success(`节点源已刷新: ${r.online}/${r.total} 在线`)
    return r
  }
  // 自动切换面板专用: 最近切换记录(不影响事件页的 eventQuery)
  const switchEvents = ref([])
  async function fetchSwitchEvents() {
    const d = await eventApi.listEvent({ pageNum: 1, pageSize: 20, type: 'auto_switch,self_heal' })
    switchEvents.value = d.rows
  }

  const config = ref(null)
  async function fetchConfig() { config.value = await sysApi.getConfig() }
  async function saveConfig(form) {
    config.value = await sysApi.putConfig(form)
    ElMessage.success('设置已保存')
  }
  // 数据源预检：只拉取/校验，不写入 config
  async function testSource(url) { return sysApi.testSource(url) }

  // 隧道自检: wg 实时状态 + 实测延迟 + 策略路由，来自网关真实命令，非缓存指标
  const tunnel = ref(null)
  async function fetchTunnel() {
    try { tunnel.value = await sysApi.getTunnel() } catch { /* 自检失败不打断页面 */ }
  }

  return {
    overview, overviewMeta, points, live, fetchOverview, startRealtime, stopRealtime,
    latencyPoints, latencyStats, latencyHead, fetchLatency,
    events, eventTotal, eventLoading, eventQuery, fetchEvents, clearEvents,
    sysInfo, fetchSysInfo, reload, restart, backup, restore,
    autoSwitch, fetchAutoSwitch, saveAutoSwitch, probeNow,
    switchEvents, fetchSwitchEvents,
    config, fetchConfig, saveConfig, testSource,
    tunnel, fetchTunnel
  }
})
