<!-- 职责: 分流规则管理页。规则组侧栏 + 规则表(拖拽排序/CRUD/启停/导入导出/命中日志)。业务动作派发 rule store。 -->
<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { useRuleStore } from '@/store/rules'
import { RULE_TYPES, RULE_ACTIONS, RULE_PATTERN_RE } from '@/constants/config'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { enableRowDrag } from '@/utils/dragSort'
import { fmtTime } from '@/utils/format'

const store = useRuleStore()
const tableRef = ref()
const tableEl = ref()
let disposeDrag = null

const typeOf = (v) => RULE_TYPES.find((t) => t.value === v) || { label: v }
const actionOf = (v) => RULE_ACTIONS.find((a) => a.value === v) || { label: v, tag: 'info' }

// ---- 分组 ----
const newGroupName = ref('')
async function submitGroup() {
  const name = newGroupName.value.trim()
  if (!name) return ElMessage.warning('请输入分组名称')
  await store.addGroup(name)
  newGroupName.value = ''
}
const delGroup = reactive({ open: false, group: null })
function askDelGroup(g) { delGroup.group = g; delGroup.open = true }

// ---- 规则编辑 ----
const dlg = reactive({ open: false, isEdit: false })
const form = ref({})
const placeholder = computed(() => typeOf(form.value.type).placeholder)
const rules = {
  type: [{ required: true, message: '请选择类型', trigger: 'change' }],
  pattern: [
    { required: true, message: '请输入匹配内容', trigger: 'blur' },
    { pattern: RULE_PATTERN_RE, message: '仅允许域名/IP/CIDR 字符', trigger: 'blur' }
  ],
  action: [{ required: true, message: '请选择动作', trigger: 'change' }]
}
function openEdit(row) {
  dlg.isEdit = !!row
  form.value = row
    ? { ...row }
    : { groupId: store.activeGroup, type: 'domain', pattern: '', action: 'proxy', remark: '', enabled: true }
  dlg.open = true
}
const formRef = ref()
async function submitEdit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  await store.save({ ...form.value, groupId: store.activeGroup }, dlg.isEdit)
  dlg.open = false
}

// ---- 启停 / 删除 ----
async function toggleEnabled(row) {
  await store.save({ ...row, enabled: row.enabled }, true)
}
const del = reactive({ open: false, ids: [] })
function askDel(rows) { del.ids = rows.map((r) => r.id); del.open = true }

// ---- 拖拽排序 ----
function bindDrag() {
  disposeDrag?.()
  const el = tableRef.value?.$el?.querySelector('.el-table__body-wrapper')
  if (!el) return
  tableEl.value = el
  disposeDrag = enableRowDrag(el, {
    onChange: (from, to) => {
      const ids = store.rows.map((r) => r.id)
      const [moved] = ids.splice(from, 1)
      ids.splice(to, 0, moved)
      store.reorder(ids)
    }
  })
}

// ---- 导入导出 ----
async function onExport() {
  const blob = new Blob([JSON.stringify(store.rows, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `rules-${store.activeGroup}-${Date.now()}.json`
  a.click(); URL.revokeObjectURL(a.href)
}
const imp = reactive({ open: false, text: '' })
async function onImport() {
  try {
    const arr = JSON.parse(imp.text)
    if (!Array.isArray(arr)) throw new Error()
    for (const r of arr) await store.save({ ...r, id: undefined, groupId: store.activeGroup }, false)
    imp.open = false; imp.text = ''
  } catch { ElMessage.error('JSON 数组格式错误') }
}

// ---- 命中日志 ----
const hitDlg = ref(false)
async function openHits(row) {
  await store.fetchHits(row.id)
  hitDlg.value = true
}

onMounted(async () => {
  await store.fetchGroups()
  if (store.activeGroup) await store.fetchRules()
  await nextTick(); bindDrag()
})
onBeforeUnmount(() => disposeDrag?.())
</script>

<template>
  <div class="gw-page rm">
    <div class="rm__aside gw-card">
      <div class="gw-card__title">规则组</div>
      <ul class="rm__groups">
        <li v-for="g in store.groups" :key="g.id"
            :class="['rm__group', { 'is-active': g.id === store.activeGroup }]"
            @click="store.selectGroup(g.id)">
          <el-icon><Folder /></el-icon>
          <span class="rm__gname">{{ g.name }}</span>
          <span class="gw-muted rm__gcount">{{ g.ruleCount ?? 0 }}</span>
          <el-button link class="rm__gdel" icon="Delete" @click.stop="askDelGroup(g)" />
        </li>
      </ul>
      <div class="rm__gadd">
        <el-input v-model="newGroupName" size="small" placeholder="新分组名" @keyup.enter="submitGroup" />
        <el-button size="small" type="primary" icon="Plus" @click="submitGroup" />
      </div>
      <!-- EXTENSION_POINT: 分组排序、分组图标选择在此扩展 -->
    </div>

    <div class="rm__main">
      <div class="gw-card rm__toolbar">
        <div class="gw-flex gw-flex--gap">
          <el-button type="primary" icon="Plus" :disabled="!store.activeGroup" @click="openEdit()">新增规则</el-button>
          <el-button icon="Upload" :disabled="!store.activeGroup" @click="imp.open = true">导入</el-button>
          <el-button icon="Download" :disabled="!store.rows.length" @click="onExport">导出</el-button>
        </div>
        <span class="gw-muted rm__hint">拖动行可调整优先级，越靠上越先生效</span>
      </div>

      <div class="gw-card rm__table">
        <el-table ref="tableRef" :data="store.rows" v-loading="store.loading" row-key="id" size="default">
          <el-table-column width="46" align="center">
            <template #default><el-icon class="rm__handle" title="拖动排序"><Rank /></el-icon></template>
          </el-table-column>
          <el-table-column label="优先级" width="80" align="center">
            <template #default="{ $index }"><span class="gw-num">{{ $index + 1 }}</span></template>
          </el-table-column>
          <el-table-column label="类型" width="100">
            <template #default="{ row }"><el-tag size="small" effect="plain">{{ typeOf(row.type).label }}</el-tag></template>
          </el-table-column>
          <el-table-column label="匹配" min-width="220">
            <template #default="{ row }"><code class="rm__pattern">{{ row.pattern }}</code></template>
          </el-table-column>
          <el-table-column label="动作" width="120">
            <template #default="{ row }"><el-tag size="small" :type="actionOf(row.action).tag">{{ actionOf(row.action).label }}</el-tag></template>
          </el-table-column>
          <el-table-column label="命中" width="90" align="right" prop="hits">
            <template #default="{ row }"><span class="gw-num">{{ row.hits ?? 0 }}</span></template>
          </el-table-column>
          <el-table-column label="最近命中" width="150">
            <template #default="{ row }"><span class="gw-muted">{{ fmtTime(row.lastHit) }}</span></template>
          </el-table-column>
          <el-table-column label="启用" width="70" align="center">
            <template #default="{ row }">
              <el-switch :model-value="row.enabled" @change="toggleEnabled(row)" />
            </template>
          </el-table-column>
          <el-table-column label="操作" width="170" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
              <el-button link type="primary" @click="openHits(row)">日志</el-button>
              <el-button link type="danger" @click="askDel([row])">删除</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <span class="gw-muted">{{ store.activeGroup ? '该分组暂无规则' : '请先选择或创建规则组' }}</span>
          </template>
        </el-table>
      </div>
    </div>

    <!-- 规则编辑 -->
    <el-dialog v-model="dlg.open" :title="dlg.isEdit ? '编辑规则' : '新增规则'" width="min(500px, 94vw)">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="类型" prop="type">
          <el-select v-model="form.type" class="rm__fill">
            <el-option v-for="t in RULE_TYPES" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="匹配" prop="pattern">
          <el-input v-model="form.pattern" :placeholder="placeholder" />
        </el-form-item>
        <el-form-item label="动作" prop="action">
          <el-radio-group v-model="form.action">
            <el-radio-button v-for="a in RULE_ACTIONS" :key="a.value" :value="a.value">{{ a.label }}</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="form.remark" maxlength="40" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.open = false">取消</el-button>
        <el-button type="primary" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 导入 -->
    <el-dialog v-model="imp.open" title="批量导入规则 (JSON 数组)" width="min(560px, 94vw)">
      <el-input v-model="imp.text" type="textarea" :rows="10"
                placeholder='[{"type":"domain","pattern":"github.com","action":"proxy","enabled":true}]' />
      <template #footer>
        <el-button @click="imp.open = false">取消</el-button>
        <el-button type="primary" @click="onImport">导入</el-button>
      </template>
    </el-dialog>

    <!-- 命中日志 -->
    <el-dialog v-model="hitDlg" title="规则命中记录" width="min(620px, 94vw)">
      <el-table :data="store.hits" size="small" max-height="360">
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ fmtTime(row.time) }}</template>
        </el-table-column>
        <el-table-column prop="client" label="客户端" width="130" />
        <el-table-column prop="query" label="请求" min-width="180" show-overflow-tooltip />
        <el-table-column label="结果" width="90">
          <template #default="{ row }"><el-tag size="small" :type="actionOf(row.action).tag">{{ actionOf(row.action).label }}</el-tag></template>
        </el-table-column>
        <template #empty><span class="gw-muted">暂无命中记录</span></template>
      </el-table>
      <!-- EXTENSION_POINT: 命中日志分页/导出处在此扩展 -->
    </el-dialog>

    <ConfirmDialog v-model="del.open" title="删除规则" danger
                   :text="`将删除 ${del.ids.length} 条规则，分流行为可能立即改变。`"
                   @confirm="store.remove(del.ids); del.open = false" />
    <ConfirmDialog v-model="delGroup.open" title="删除规则组" danger
                   :text="`删除「${delGroup.group?.name}」会同时移除组内所有规则。`"
                   @confirm="store.removeGroup(delGroup.group.id); delGroup.open = false" />
  </div>
</template>

<style scoped>
.rm {
  display: grid; grid-template-columns: 220px 1fr; gap: 12px; align-items: start;
}
.rm__aside { padding: 12px; }
.rm__groups { list-style: none; margin: 10px 0; padding: 0; }
.rm__group {
  display: flex; align-items: center; gap: 6px; padding: 7px 8px;
  border-radius: var(--gw-radius-sm); cursor: pointer; font-size: 13px;
  transition: background var(--gw-dur-fast) var(--gw-ease);
}
.rm__group:hover { background: var(--gw-card-hover); }
.rm__group.is-active {
  background: var(--gw-accent-soft);
  color: var(--gw-accent);
}
.rm__gname { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rm__gcount { font-size: 12px; }
.rm__gdel { opacity: 0; transition: opacity var(--gw-dur-fast) var(--gw-ease); }
.rm__group:hover .rm__gdel { opacity: 0.7; }
.rm__gadd { display: flex; gap: 6px; }

.rm__main { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.rm__toolbar {
  display: flex; flex-wrap: wrap; gap: 10px; justify-content: space-between; align-items: center; padding: 12px 14px;
}
.rm__hint { font-size: 12px; }
.rm__table { padding: 4px 10px 10px; }
.rm__handle { color: var(--gw-text-3); cursor: grab; }
.rm__pattern {
  font-family: var(--gw-font-mono); font-size: 12.5px; color: var(--gw-text-1);
  background: var(--gw-bg-soft); padding: 2px 6px; border-radius: var(--gw-radius-sm);
}
.rm__fill { width: 100%; }

@media (max-width: 768px) {
  .rm { grid-template-columns: 1fr; }
}
</style>
