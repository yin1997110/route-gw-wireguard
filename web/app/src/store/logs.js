// 职责: 日志查看器域状态——白名单日志源、按行数/关键字取回、可选自动跟随。
// 自动刷新默认关闭：journalctl 每次都要 fork 进程，1 核机器上没必要一直跟着跑。
import { defineStore } from 'pinia'
import { ref, reactive, computed } from 'vue'
import * as sysApi from '@/api/system'
import { LOGS } from '@/constants/config'

export const useLogStore = defineStore('logs', () => {
  const units = ref([])
  const rows = ref([])
  const meta = ref({})
  const loading = ref(false)
  const query = reactive({ unit: 'dnsmasq', lines: LOGS.DEFAULT_LINES, keyword: '' })
  const follow = ref(false)

  const currentUnit = computed(() => units.value.find((u) => u.key === query.unit) || null)

  async function fetchUnits() { units.value = await sysApi.getLogUnits() }

  async function fetchLogs({ silent } = {}) {
    if (!silent) loading.value = true
    try {
      const d = await sysApi.getLogs(query)
      rows.value = d.lines
      meta.value = { unit: d.unit, label: d.label, source: d.source, scanned: d.scanned, matched: d.matched }
    } finally { loading.value = false }
  }

  function resetPage() { rows.value = []; fetchLogs() }

  let timer = null
  function startFollow() { stopFollow(); timer = setInterval(() => fetchLogs({ silent: true }), LOGS.POLL * 1000) }
  function stopFollow() { if (timer) { clearInterval(timer); timer = null } }
  function setFollow(on) {
    follow.value = on
    if (on) startFollow(); else stopFollow()
  }

  return { units, rows, meta, loading, query, follow, currentUnit, fetchUnits, fetchLogs, resetPage, setFollow, stopFollow }
})
