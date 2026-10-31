// 职责: DNS 观测域状态——分流配置概览、分上游解析对比、规则命中流水。视图只渲染与派发，不直接调 api。
import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import * as dnsApi from '@/api/dns'
import { DNS } from '@/constants/config'

export const useDnsStore = defineStore('dns', () => {
  const overview = ref(null)
  const loading = ref(false)
  const testing = ref(false)
  const test = reactive({ domain: '', type: 'A', view: 'all', results: [], matches: [] })
  const hits = ref([])

  async function fetchOverview({ silent } = {}) {
    if (!silent) loading.value = true
    try {
      overview.value = await dnsApi.getDnsOverview()
    } finally { loading.value = false }
  }

  async function runQuery() {
    const name = String(test.domain || '').trim()
    if (!name) { ElMessage.warning('先输入要测试的域名'); return }
    testing.value = true
    try {
      const d = await dnsApi.queryDns({ domain: name, type: test.type, view: test.view })
      test.results = d.results
      test.matches = d.matches
    } finally { testing.value = false }
  }

  async function fetchHits() {
    const d = await dnsApi.getDnsHits({ limit: DNS.HIT_LIMIT })
    hits.value = d.rows
  }

  // 命中流水是持续产生的：页面停留期间跟着轮询，离开页面由视图 stopPoll
  let timer = null
  function startPoll() { stopPoll(); timer = setInterval(() => fetchHits(), DNS.HIT_POLL * 1000) }
  function stopPoll() { if (timer) { clearInterval(timer); timer = null } }

  return {
    overview, loading, testing, test, hits,
    fetchOverview, runQuery, fetchHits, startPoll, stopPoll
  }
})

// EXTENSION_POINT: 自定义域名下发/DNS 重载等写动作在此扩展(当前面板只做观测)