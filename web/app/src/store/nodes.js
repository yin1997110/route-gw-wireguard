// 职责: 节点域状态与业务动作(CRUD/切换/订阅/导入导出)。组件不直接调 api。
import { defineStore } from 'pinia'
import { ref, reactive, computed } from 'vue'
import { ElMessage } from 'element-plus'
import * as nodeApi from '@/api/node'
import * as subApi from '@/api/subscription'
import { PAGINATION, REFRESH } from '@/constants/config'

export const useNodeStore = defineStore('nodes', () => {
  const rows = ref([])
  const total = ref(0)
  const loading = ref(false)
  const query = reactive({ pageNum: 1, pageSize: PAGINATION.PAGE_SIZE, group: '', status: '', keyword: '' })

  const current = computed(() => rows.value.find((n) => n.current) || null)
  const onlineCount = computed(() => rows.value.filter((n) => n.status === 'online').length)
  // 分组全集优先取后端(节点数千，只按当前页推导会让筛选器缺项)；未提供时回退本页推导
  const serverGroups = ref([])
  const groups = computed(() => serverGroups.value.length
    ? serverGroups.value
    : [...new Set(rows.value.map((n) => n.group).filter(Boolean))])

  async function fetchList({ silent } = {}) {
    if (!silent) loading.value = true
    try {
      const data = await nodeApi.listNode(query)
      rows.value = data.rows
      total.value = data.total
      if (data.groups?.length) serverGroups.value = data.groups
    } finally { loading.value = false }
  }

  // 全局单例轮询：顶栏常驻显示当前节点延迟，布局挂载期间持续刷新
  let timer = null
  function startPoll() {
    stopPoll()
    timer = setInterval(() => fetchList({ silent: true }), REFRESH.NODE_POLL * 1000)
  }
  function stopPoll() { if (timer) { clearInterval(timer); timer = null } }

  async function switchTo(id) {
    await nodeApi.switchNode(id)
    ElMessage.success('已下发切换')
    await fetchList()
  }
  async function save(form, isEdit) {
    if (isEdit) await nodeApi.updateNode(form)
    else await nodeApi.addNode(form)
    ElMessage.success(isEdit ? '已保存' : '已新增')
    await fetchList()
  }
  async function remove(ids) {
    await nodeApi.delNode(ids)
    ElMessage.success('已删除')
    await fetchList()
  }
  async function exportRows() { return nodeApi.exportNode() }
  async function importRows(rowsIn) {
    const r = await nodeApi.importNode(rowsIn)
    ElMessage.success(`导入完成: 新增 ${r.added}，跳过 ${r.skipped}`)
    await fetchList()
  }

  // ---- 订阅 ----
  const subs = ref([])
  async function fetchSubs() { subs.value = await subApi.listSub() }
  async function fetchSub(id) {
    const r = await subApi.fetchSub(id)
    ElMessage.success(`订阅更新: 新增 ${r.added} 个节点`)
    await Promise.all([fetchList(), fetchSubs()])
  }
  async function addSub(data) { await subApi.addSub(data); await fetchSubs() }
  async function delSub(id) { await subApi.delSub(id); await fetchSubs() }

  return {
    rows, total, loading, query, current, onlineCount, groups,
    fetchList, switchTo, save, remove, exportRows, importRows,
    startPoll, stopPoll,
    subs, fetchSubs, fetchSub, addSub, delSub
  }
})
