<!-- 职责: 切换历史页。把事件流里"发起切换 → 握手/回滚结果"配对成时间线，只读展示结论与耗时。 -->
<script setup>
import { computed, onMounted } from 'vue'
import { useSwitchLogStore } from '@/store/switchlog'
import { SWITCH_RESULT, PAGINATION } from '@/constants/config'
import DelayBadge from '@/components/DelayBadge.vue'
import { fmtTime } from '@/utils/format'

const sw = useSwitchLogStore()

const resultOf = (v) => SWITCH_RESULT.find((r) => r.value === v) || { label: v, tag: 'info' }
const chips = computed(() => [
  { key: 'total', label: '切换次数', value: sw.summary.total ?? 0, tone: 'var(--gw-accent)' },
  { key: 'success', label: '成功', value: sw.summary.success ?? 0, tone: 'var(--gw-success)' },
  { key: 'fail', label: '失败/回滚', value: sw.summary.fail ?? 0, tone: 'var(--gw-danger)' },
  { key: 'pending', label: '无结果', value: sw.summary.pending ?? 0, tone: 'var(--gw-text-3)' },
  { key: 'cost', label: '平均耗时', value: sw.summary.avgCost == null ? '—' : `${sw.summary.avgCost}s`, tone: 'var(--gw-warning)' }
])
// 结论筛选走后端，本页数据来自事件流而非分页接口，翻页时保持同一筛选条件
function search() { sw.query.pageNum = 1; sw.fetchList() }

onMounted(() => sw.fetchList())
// EXTENSION_POINT: 切换成功率按天聚合、导出 CSV 在此扩展
</script>

<template>
  <div class="gw-page sh">
    <div class="gw-card sh__head">
      <div class="sh__chips">
        <div v-for="c in chips" :key="c.key" class="sh__chip">
          <span class="gw-muted">{{ c.label }}</span>
          <b class="gw-num" :style="{ color: c.tone }">{{ c.value }}</b>
        </div>
      </div>
      <ul class="sh__kv">
        <li><span>当前节点</span><b>{{ sw.head.current || '—' }}</b></li>
        <li><span>最近切换</span><b class="gw-num">{{ fmtTime(sw.head.lastSwitchAt) }}</b></li>
        <li>
          <span>自动切换</span>
          <b><el-tag size="small" :type="sw.head.autoswitch.enabled ? 'success' : 'info'" effect="light">
            {{ sw.head.autoswitch.enabled ? `已开启 · ${sw.head.autoswitch.interval}s` : '已关闭' }}
          </el-tag></b>
        </li>
      </ul>
    </div>

    <div class="gw-card sh__toolbar">
      <div class="gw-flex gw-flex--gap">
        <el-select v-model="sw.query.result" placeholder="全部结论" clearable class="sh__sel" @change="search">
          <el-option v-for="r in SWITCH_RESULT" :key="r.value" :label="r.label" :value="r.value" />
        </el-select>
        <el-input v-model="sw.query.keyword" placeholder="搜索节点/原因" clearable class="sh__kw"
                  @keyup.enter="search" @clear="search" />
        <el-button type="primary" icon="Search" @click="search">查询</el-button>
      </div>
      <el-button plain icon="Refresh" :loading="sw.loading" @click="sw.fetchList()">刷新</el-button>
    </div>

    <div class="gw-card sh__table">
      <el-table :data="sw.rows" v-loading="sw.loading">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="sh__detail">
              <p><span class="gw-muted">发起记录</span>{{ row.attemptMsg || '—' }}</p>
              <p><span class="gw-muted">结果记录</span>{{ row.outcomeMsg || '尚无结果事件（可能仍在握手或已超时）' }}</p>
              <p><span class="gw-muted">事件 ID</span><span class="gw-num">{{ row.id }}</span></p>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="160">
          <template #default="{ row }"><span class="gw-num">{{ fmtTime(row.at) }}</span></template>
        </el-table-column>
        <el-table-column label="触发" width="90">
          <template #default="{ row }"><span class="gw-muted">{{ row.trigger }}</span></template>
        </el-table-column>
        <el-table-column label="源 → 目标" min-width="230" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="gw-num">{{ row.from || '—' }}</span>
            <span class="sh__arrow">→</span>
            <span class="gw-num sh__to">{{ row.to || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="结论" width="100">
          <template #default="{ row }"><el-tag size="small" :type="resultOf(row.result).tag">{{ resultOf(row.result).label }}</el-tag></template>
        </el-table-column>
        <el-table-column label="耗时" width="90">
          <template #default="{ row }"><span class="gw-num">{{ row.cost == null ? '—' : `${row.cost}s` }}</span></template>
        </el-table-column>
        <el-table-column label="切换后延迟" width="150">
          <template #default="{ row }"><DelayBadge :delay="row.latency" :loss="row.loss || 0" /></template>
        </el-table-column>
        <el-table-column prop="reason" label="原因" min-width="180" show-overflow-tooltip>
          <template #default="{ row }"><span class="gw-muted">{{ row.reason || '—' }}</span></template>
        </el-table-column>
        <template #empty><span class="gw-muted">暂无切换记录</span></template>
      </el-table>
      <el-pagination class="sh__page" layout="total, sizes, prev, pager, next" background
                     :total="sw.total" v-model:current-page="sw.query.pageNum"
                     v-model:page-size="sw.query.pageSize" :page-sizes="PAGINATION.PAGE_SIZES"
                     @current-change="sw.fetchList()" @size-change="sw.fetchList()" />
    </div>
  </div>
</template>

<style scoped>
.sh__head { display: flex; flex-wrap: wrap; gap: 16px; justify-content: space-between; align-items: center; padding: 14px 16px; margin-bottom: 12px; }
.sh__chips { display: flex; flex-wrap: wrap; gap: 22px; }
.sh__chip { display: flex; flex-direction: column; gap: 2px; }
.sh__chip b { font-size: 19px; font-weight: 700; }
.sh__kv { list-style: none; margin: 0; padding: 0; display: flex; gap: 20px; flex-wrap: wrap; font-size: 13px; }
.sh__kv li { display: flex; gap: 8px; align-items: center; }
.sh__kv b { color: var(--gw-text-1); font-weight: 600; }
.sh__toolbar {
  display: flex; flex-wrap: wrap; gap: 10px; justify-content: space-between; align-items: center;
  padding: 12px 14px; margin-bottom: 12px;
}
.sh__sel { width: 130px; }
.sh__kw { width: 200px; }
.sh__table { padding: 4px 10px 10px; }
.sh__page { margin-top: 10px; justify-content: flex-end; }
.sh__arrow { margin: 0 8px; color: var(--gw-text-3); }
.sh__to { font-weight: 600; }
.sh__detail { padding: 6px 16px; font-size: 12px; color: var(--gw-text-2); }
.sh__detail p { margin: 4px 0; display: flex; gap: 8px; }
.sh__detail span { color: var(--gw-text-3); flex-shrink: 0; }
</style>
