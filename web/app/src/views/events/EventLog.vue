<!-- 职责: 事件日志页。仅关键事件(切换/故障/订阅/系统操作)，支持类型与关键字筛选、分页、一键清空。 -->
<script setup>
import { reactive, onMounted } from 'vue'
import { useSystemStore } from '@/store/system'
import { EVENT_TYPES, PAGINATION } from '@/constants/config'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { fmtTime } from '@/utils/format'

const sys = useSystemStore()
const clearBox = reactive({ open: false })

const typeOf = (v) => EVENT_TYPES.find((t) => t.value === v) || { label: v, tag: 'info' }

onMounted(() => sys.fetchEvents())
// EXTENSION_POINT: 日志导出、按时间范围筛选在此扩展
</script>

<template>
  <div class="gw-page el">
    <div class="gw-card el__toolbar">
      <div class="gw-flex gw-flex--gap">
        <el-select v-model="sys.eventQuery.type" placeholder="全部类型" clearable class="el__sel" @change="sys.fetchEvents()">
          <el-option v-for="t in EVENT_TYPES" :key="t.value" :label="t.label" :value="t.value" />
        </el-select>
        <el-input v-model="sys.eventQuery.keyword" placeholder="搜索节点/信息" clearable class="el__kw"
                  @keyup.enter="sys.fetchEvents()" @clear="sys.fetchEvents()" />
        <el-button type="primary" icon="Search" @click="sys.fetchEvents()">查询</el-button>
      </div>
      <el-button type="danger" plain icon="Delete" :disabled="!sys.events.length" @click="clearBox.open = true">一键清空</el-button>
    </div>

    <div class="gw-card el__table">
      <el-table :data="sys.events" v-loading="sys.eventLoading">
        <el-table-column type="expand">
          <template #default="{ row }">
            <pre class="el__detail">{{ row.detail || '无附加信息' }}</pre>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="170">
          <template #default="{ row }"><span class="gw-num">{{ fmtTime(row.time) }}</span></template>
        </el-table-column>
        <el-table-column label="类型" width="110">
          <template #default="{ row }"><el-tag size="small" :type="typeOf(row.type).tag">{{ typeOf(row.type).label }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="message" label="事件" min-width="300" show-overflow-tooltip />
        <el-table-column label="来源" width="130">
          <template #default="{ row }"><span class="gw-muted">{{ row.source || '系统' }}</span></template>
        </el-table-column>
        <template #empty><span class="gw-muted">暂无关键事件</span></template>
      </el-table>
      <el-pagination class="el__page" layout="total, sizes, prev, pager, next" background
                     :total="sys.eventTotal" v-model:current-page="sys.eventQuery.pageNum"
                     v-model:page-size="sys.eventQuery.pageSize" :page-sizes="PAGINATION.PAGE_SIZES"
                     @current-change="sys.fetchEvents()" @size-change="sys.fetchEvents()" />
    </div>

    <ConfirmDialog v-model="clearBox.open" title="清空事件日志" danger
                   text="将删除全部历史事件记录，清空后无法找回。"
                   @confirm="sys.clearEvents(); clearBox.open = false" />
  </div>
</template>

<style scoped>
.el__toolbar {
  display: flex; flex-wrap: wrap; gap: 10px; justify-content: space-between; align-items: center;
  padding: 12px 14px; margin-bottom: 12px;
}
.el__kw { width: 200px; }
.el__sel { width: 140px; }
.el__table { padding: 4px 10px 10px; }
.el__page { margin-top: 10px; justify-content: flex-end; }
.el__detail {
  margin: 0; padding: 10px 14px; font-family: var(--gw-font-mono); font-size: 12px;
  color: var(--gw-text-2); background: var(--gw-bg-soft); border-radius: var(--gw-radius-sm);
  white-space: pre-wrap; word-break: break-all;
}
</style>
