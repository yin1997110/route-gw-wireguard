// 职责: 分流数据源域状态——国内 IP 明细/gfwlist/更新脚本与定时任务的状态，以及"跑一次更新脚本"。
// 更新动作复用网关既有的 update-lists.sh，面板不重写下载逻辑，失败也只回显脚本输出。
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as subApi from '@/api/subscription'
import { LIST_VIEW } from '@/constants/config'

export const useListStore = defineStore('lists', () => {
  const status = ref(null)
  const loading = ref(false)
  const updating = ref(false)

  async function fetchStatus({ silent } = {}) {
    if (!silent) loading.value = true
    try {
      status.value = await subApi.getListStatus()
    } finally { loading.value = false }
  }

  async function runUpdate() {
    updating.value = true
    try {
      const r = await subApi.updateLists()
      if (r.rc === 0) ElMessage.success(`更新完成: 国内 IP ${r.china} 条 / 域名 ${r.gfw} 条`)
      else ElMessage.warning(`脚本返回 rc=${r.rc}，详见更新日志`)
      await fetchStatus({ silent: true })
      return r
    } finally { updating.value = false }
  }

  // 数据源本身由 cron 更新，面板只做低频状态刷新
  let timer = null
  function startPoll() { stopPoll(); timer = setInterval(() => fetchStatus({ silent: true }), LIST_VIEW.POLL * 1000) }
  function stopPoll() { if (timer) { clearInterval(timer); timer = null } }

  return { status, loading, updating, fetchStatus, runUpdate, startPoll, stopPoll }
})
