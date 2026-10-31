// 职责: 切换历史域状态——把事件流里"发起切换 → 握手结果"配对成可筛选的时间线。只读。
import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import * as eventApi from '@/api/event'
import { PAGINATION } from '@/constants/config'

export const useSwitchLogStore = defineStore('switchlog', () => {
  const rows = ref([])
  const total = ref(0)
  const loading = ref(false)
  const summary = ref({})
  const head = ref({ current: null, lastSwitchAt: 0, autoswitch: {} })
  const query = reactive({ pageNum: 1, pageSize: PAGINATION.PAGE_SIZE, result: '', keyword: '' })

  async function fetchList({ silent } = {}) {
    if (!silent) loading.value = true
    try {
      const d = await eventApi.listSwitchHistory(query)
      rows.value = d.rows
      total.value = d.total
      summary.value = d.summary
      head.value = { current: d.current, lastSwitchAt: d.lastSwitchAt, autoswitch: d.autoswitch }
    } finally { loading.value = false }
  }

  return { rows, total, loading, summary, head, query, fetchList }
})
