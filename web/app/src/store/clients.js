// 职责: 客户端设备观测域状态——邻居表/租约/DNS 活跃度合并出的设备列表与低频轮询。
import { defineStore } from 'pinia'
import { ref, reactive, computed } from 'vue'
import * as clientApi from '@/api/client'
import { PAGINATION, CLIENT_VIEW } from '@/constants/config'

export const useClientStore = defineStore('clients', () => {
  const rows = ref([])
  const total = ref(0)
  const loading = ref(false)
  const stat = ref({})
  const query = reactive({ pageNum: 1, pageSize: PAGINATION.PAGE_SIZE, keyword: '', active: '' })

  const activeCount = computed(() => rows.value.filter((r) => r.active).length)

  async function fetchList({ silent } = {}) {
    if (!silent) loading.value = true
    try {
      const params = { ...query }
      if (!params.active) delete params.active
      const d = await clientApi.listClient(params)
      rows.value = d.rows
      total.value = d.total
      stat.value = d.stat
    } finally { loading.value = false }
  }

  function setFilter(which) {
    query.active = which ? '1' : ''
    query.pageNum = 1
    fetchList()
  }

  // 设备表变化不快，10s 轮询够跟住"谁在上网"，也不会给 1 核机器加活
  let timer = null
  function startPoll() { stopPoll(); timer = setInterval(() => fetchList({ silent: true }), CLIENT_VIEW.POLL * 1000) }
  function stopPoll() { if (timer) { clearInterval(timer); timer = null } }

  return { rows, total, loading, stat, query, activeCount, fetchList, setFilter, startPoll, stopPoll }
})