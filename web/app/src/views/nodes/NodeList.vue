<!-- 职责: 节点管理页。列表/筛选/CRUD/手动切换/导入导出/订阅管理。业务动作全部派发 node store。 -->
<script setup>
import { ref, reactive, computed, onActivated } from 'vue'
import { ElMessage } from 'element-plus'
import { useNodeStore } from '@/store/nodes'
import { PAGINATION, APP, SWITCH } from '@/constants/config'
import StatusTag from '@/components/StatusTag.vue'
import DelayBadge from '@/components/DelayBadge.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { fmtBytes, fmtTime } from '@/utils/format'

const store = useNodeStore()
const sel = ref([])
// 仓库里的常量是占位值，真实矩阵地址以接口回传为准
const nodeSource = computed(() => store.nodeSource || APP.NODE_SOURCE_HOME)

// ---- 编辑对话框 ----
const dlg = reactive({ open: false, isEdit: false })
const form = ref({})
const rules = {
  name: [{ required: true, message: '请输入节点名称', trigger: 'blur' }],
  server: [{ required: true, message: '请输入服务器地址', trigger: 'blur' }]
}
function openEdit(row) {
  dlg.isEdit = !!row
  form.value = row ? { ...row } : { name: '', server: '', port: 51820, group: '默认组', country: '', city: '', flag: '🌐' }
  dlg.open = true
}
const formRef = ref()
async function submitEdit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  await store.save(form.value, dlg.isEdit)
  dlg.open = false
}

// ---- 切换(同区域优先提示) ----
const sw = reactive({ open: false, row: null })
function askSwitch(row) {
  if (row.current) return ElMessage.info('该节点已是当前节点')
  sw.row = row; sw.open = true
}
async function doSwitch() {
  await store.switchTo(sw.row.id)
  sw.open = false
}
function sameRegionTip(row) {
  const cur = store.current
  return cur && row.country === cur.country
}

// ---- 导入导出 ----
async function onExport() {
  const rows = await store.exportRows()
  const blob = new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `nodes-${Date.now()}.json`
  a.click(); URL.revokeObjectURL(a.href)
}
const imp = reactive({ open: false, text: '' })
async function onImport() {
  try {
    const arr = JSON.parse(imp.text)
    if (!Array.isArray(arr)) throw new Error()
    await store.importRows(arr)
    imp.open = false; imp.text = ''
  } catch { ElMessage.error('JSON 数组格式错误') }
}

// ---- 订阅管理 ----
const subDlg = ref(false)
const subForm = ref({ name: '', url: '', autoFetch: true })
async function doFetchSub(id) { await store.fetchSub(id) }

const del = reactive({ open: false, ids: [] })
function askDel(rows) { del.ids = rows.map((r) => r.id); del.open = true }

const pageInfo = computed(() => ({
  page: store.query.pageNum, size: store.query.pageSize
}))

// 列表轮询由布局持有(store.startPoll)；此处只在进入页面时立即刷新一次
onActivated(() => { store.fetchList(); store.fetchSubs() })
</script>

<template>
  <div class="gw-page nl">
    <!-- 来源说明条 -->
    <div class="gw-card nl__srcbar">
      <el-icon><InfoFilled /></el-icon>
      节点主数据来源矩阵页
      <el-link type="primary" underline="never" :href="nodeSource" target="_blank">{{ nodeSource }}</el-link>
      <span class="gw-muted">· 自动切换按「同国家/城市优先」策略执行 (冷却 {{ SWITCH.COOLDOWN }}s)</span>
    </div>

    <!-- 筛选 + 工具条 -->
    <div class="gw-card nl__toolbar">
      <div class="gw-flex gw-flex--gap nl__filters">
        <el-input v-model="store.query.keyword" placeholder="搜索名称/地址" clearable class="nl__kw"
                  @keyup.enter="store.fetchList()" @clear="store.fetchList()" />
        <el-select v-model="store.query.group" placeholder="分组" clearable class="nl__sel" @change="store.fetchList()">
          <el-option v-for="g in store.groups" :key="g" :label="g" :value="g" />
        </el-select>
        <el-select v-model="store.query.status" placeholder="状态" clearable class="nl__sel" @change="store.fetchList()">
          <el-option label="在线" value="online" /><el-option label="离线" value="offline" /><el-option label="故障" value="fault" />
        </el-select>
        <el-button type="primary" icon="Search" @click="store.fetchList()">查询</el-button>
      </div>
      <div class="gw-flex gw-flex--gap">
        <el-button type="primary" icon="Plus" @click="openEdit()">新增</el-button>
        <el-button icon="Upload" @click="imp.open = true">导入</el-button>
        <el-button icon="Download" @click="onExport">导出</el-button>
        <el-button icon="Refresh" @click="subDlg = true">订阅</el-button>
        <el-button type="danger" plain icon="Delete" :disabled="!sel.length" @click="askDel(sel)">删除</el-button>
      </div>
    </div>

    <!-- 表格 -->
    <div class="gw-card nl__table">
      <el-table :data="store.rows" v-loading="store.loading" @selection-change="sel = $event"
                :row-class-name="({ row }) => (row.current ? 'current-node-row' : '')" @sort-change="() => {}">
        <el-table-column type="selection" width="42" />
        <el-table-column label="节点" min-width="200">
          <template #default="{ row }">
            <div class="gw-flex gw-flex--gap">
              <span class="nl__flag">{{ row.flag }}</span>
              <div>
                <div class="nl__name">{{ row.name }}<el-tag v-if="row.current" size="small" class="nl__cur">当前</el-tag></div>
                <div class="gw-muted">{{ row.server }}:{{ row.port }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="group" label="分组" width="100" />
        <el-table-column label="地区" width="140">
          <template #default="{ row }">{{ row.country }} · {{ row.city }}<el-icon v-if="sameRegionTip(row)" class="nl__same" title="与当前节点同区域"><Aim /></el-icon></template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }"><StatusTag :status="row.status" /></template>
        </el-table-column>
        <el-table-column label="延迟" width="120" align="center" prop="delay" sortable>
          <template #default="{ row }"><DelayBadge :delay="row.delay" :loss="row.loss" /></template>
        </el-table-column>
        <el-table-column label="上/下行" width="150">
          <template #default="{ row }"><span class="gw-num nl__flow">↑{{ fmtBytes(row.upBytes) }} ↓{{ fmtBytes(row.downBytes) }}</span></template>
        </el-table-column>
        <el-table-column label="最后探测" width="130">
          <template #default="{ row }"><span class="gw-muted">{{ fmtTime(row.lastCheck) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :disabled="row.status !== 'online' || row.current" @click="askSwitch(row)">切换</el-button>
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="askDel([row])">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination class="nl__page" layout="total, sizes, prev, pager, next" background
                     :total="store.total" v-model:current-page="store.query.pageNum"
                     v-model:page-size="store.query.pageSize" :page-sizes="PAGINATION.PAGE_SIZES"
                     @current-change="store.fetchList()" @size-change="store.fetchList()" />
    </div>

    <!-- 新增/编辑 -->
    <el-dialog v-model="dlg.open" :title="dlg.isEdit ? '编辑节点' : '新增节点'" width="min(480px, 94vw)">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="88px">
        <el-form-item label="名称" prop="name"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="服务器" prop="server"><el-input v-model="form.server" /></el-form-item>
        <el-form-item label="端口"><el-input-number v-model="form.port" :min="1" :max="65535" /></el-form-item>
        <el-form-item label="分组"><el-input v-model="form.group" /></el-form-item>
        <el-form-item label="国家"><el-input v-model="form.country" placeholder="如 美国" /></el-form-item>
        <el-form-item label="城市"><el-input v-model="form.city" placeholder="如 洛杉矶" /></el-form-item>
        <el-form-item label="旗帜"><el-input v-model="form.flag" maxlength="4" placeholder="emoji，如 🇺🇸" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.open = false">取消</el-button>
        <el-button type="primary" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 导入 -->
    <el-dialog v-model="imp.open" title="批量导入 (JSON 数组)" width="min(560px, 94vw)">
      <el-input v-model="imp.text" type="textarea" :rows="10"
                placeholder='[{"name":"xx","server":"1.2.3.4","port":51820,"group":"默认组","country":"美国","city":"洛杉矶","flag":"🇺🇸"}]' />
      <template #footer>
        <el-button @click="imp.open = false">取消</el-button>
        <el-button type="primary" @click="onImport">导入</el-button>
      </template>
    </el-dialog>

    <!-- 订阅管理 -->
    <el-dialog v-model="subDlg" title="订阅管理" width="min(620px, 94vw)">
      <div class="nl__sub-add gw-flex gw-flex--gap gw-mb">
        <el-input v-model="subForm.name" placeholder="备注名" class="nl__sel" />
        <el-input v-model="subForm.url" placeholder="订阅链接 (https://...)" />
        <el-button type="primary" :disabled="!subForm.url"
                   @click="store.addSub({ ...subForm }); subForm = { name: '', url: '', autoFetch: true }">添加</el-button>
      </div>
      <el-table :data="store.subs" size="small">
        <el-table-column prop="name" label="名称" width="120" />
        <el-table-column prop="url" label="链接" show-overflow-tooltip min-width="180" />
        <el-table-column label="上次拉取" width="150">
          <template #default="{ row }"><span class="gw-muted">{{ fmtTime(row.lastFetch) }}</span></template>
        </el-table-column>
        <el-table-column label="自动" width="70" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="row.autoFetch ? 'success' : 'info'">{{ row.autoFetch ? '开' : '关' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="doFetchSub(row.id)">拉取</el-button>
            <el-button link type="danger" @click="store.delSub(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <!-- EXTENSION_POINT: 订阅拉取周期编辑、节点转换协议选择在此扩展 -->
    </el-dialog>

    <ConfirmDialog v-model="sw.open" title="切换节点" danger
                   :text="`确认切换到「${sw.row?.name}」？切换期间隧道将短暂中断(约 2~5s)。`"
                   @confirm="doSwitch" />
    <ConfirmDialog v-model="del.open" title="删除节点" danger
                   :text="`将删除 ${del.ids.length} 个节点，操作不可恢复。`"
                   @confirm="store.remove(del.ids); del.open = false" />
  </div>
</template>

<style scoped>
.nl__srcbar {
  display: flex; align-items: center; gap: 8px; padding: 10px 14px; margin-bottom: 12px;
  font-size: 13px; color: var(--gw-text-2);
}
.nl__toolbar {
  display: flex; flex-wrap: wrap; gap: 10px; justify-content: space-between;
  align-items: center; padding: 12px 14px; margin-bottom: 12px;
}
.nl__filters { display: flex; flex-wrap: wrap; gap: 10px; }
.nl__kw { width: 190px; }
.nl__sel { width: 130px; }
.nl__table { padding: 4px 10px 10px; }
.nl__flag { font-size: 20px; }
.nl__name { font-weight: 600; display: flex; align-items: center; gap: 6px; }
.nl__cur { color: var(--gw-accent); }
.nl__same { color: var(--gw-success); margin-left: 4px; }
.nl__flow { font-size: 12px; color: var(--gw-text-2); }
.nl__page { margin-top: 10px; justify-content: flex-end; }
</style>
