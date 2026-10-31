// 职责: 分流规则域状态(规则组/规则/排序/命中日志)。
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as ruleApi from '@/api/rule'

export const useRuleStore = defineStore('rules', () => {
  const groups = ref([])
  const activeGroup = ref(null)
  const rows = ref([])
  const loading = ref(false)
  const hits = ref([])

  async function fetchGroups() {
    groups.value = await ruleApi.listRuleGroup()
    if (activeGroup.value === null && groups.value.length) activeGroup.value = groups.value[0].id
  }
  async function fetchRules() {
    loading.value = true
    try { rows.value = await ruleApi.listRule({ groupId: activeGroup.value }) }
    finally { loading.value = false }
  }
  async function selectGroup(id) { activeGroup.value = id; await fetchRules() }

  async function addGroup(name) {
    await ruleApi.addRuleGroup({ name })
    ElMessage.success('分组已创建')
    await fetchGroups()
  }
  async function removeGroup(id) {
    await ruleApi.delRuleGroup(id)
    if (activeGroup.value === id) activeGroup.value = null
    await fetchGroups()
    if (groups.value.length) await selectGroup(groups.value[0].id)
    else rows.value = []
  }

  async function save(form, isEdit) {
    if (isEdit) await ruleApi.updateRule(form)
    else await ruleApi.addRule(form)
    ElMessage.success(isEdit ? '规则已更新' : '规则已添加')
    await fetchRules()
  }
  async function remove(ids) {
    await ruleApi.delRule(ids)
    ElMessage.success('已删除')
    await fetchRules()
  }
  /** 拖拽后按新顺序重排优先级(整组提交，避免中间态) */
  async function reorder(orderedIds) {
    await ruleApi.reorderRule({ groupId: activeGroup.value, ids: orderedIds })
    await fetchRules()
  }
  async function fetchHits(ruleId) { hits.value = await ruleApi.listRuleHit({ ruleId }) }

  return {
    groups, activeGroup, rows, loading, hits,
    fetchGroups, fetchRules, selectGroup, addGroup, removeGroup,
    save, remove, reorder, fetchHits
  }
})
