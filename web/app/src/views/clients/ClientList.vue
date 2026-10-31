<!-- 职责: 客户端设备页。把 ARP 邻居表、dnsmasq 租约与 DNS 查询活跃度合成一张"谁在用什么"的表。
     只读观测：不做设备限速、不下发任何策略。 -->
<script setup>
import { computed, onActivated, onDeactivated } from 'vue'
import { useClientStore } from '@/store/clients'
import { PAGINATION, CLIENT_VIEW } from '@/constants/config'
import { fmtTime, fmtDuration } from '@/utils/format'

const clients = useClientStore()

const chips = computed(() => {
  const s = clients.stat || {}
  return [
    { label: '设备总数', value: s.total ?? 0 },
    { label: `${Math.round((s.activeWindow || 180) / 60)} 分钟内活跃`, value: s.active ?? 0 },
    { label: '邻居表条目', value: s.neigh ?? 0 },
    { label: 'DHCP 租约', value: s.leases ?? 0 },
    { label: '走隧道查询', value: s.proxyTotal ?? 0 },
    { label: '走直连查询', value: s.directTotal ?? 0 }
  ]
})

const stateTag = (st) => ({
  REACHABLE: 'success', STALE: 'info', DELAY: 'info', PROBE: 'warning',
  FAILED: 'danger', INCOMPLETE: 'danger', PERMANENT: 'success', NOARP: 'info'
}[st] || 'info')

function toggleFilter() {
  clients.setFilter(!clients.query.active)
}

onActivated(() => {
  clients.fetchList()
  clients.startPoll()
})
onDeactivated(() => clients.stopPoll())
// EXTENSION_POINT: 设备备注/分组(需要新增后端存储)在此扩展
</script>

<template>
  <div class="gw-page cl">
    <div class="gw-card cl__toolbar">
      <div class="gw-flex gw-flex--gap cl__filters">
        <el-input v-model="clients.query.keyword" placeholder="搜索 IP / MAC / 主机名 / 域名" clearable
                  class="cl__kw" @keyup.enter="clients.fetchList()" @clear="clients.fetchList()" />
        <el-button type="primary" icon="Search" @click="clients.fetchList()">查询</el-button>
        <el-button :type="clients.query.active ? 'primary' : 'default'" plain icon="Monitor"
                   @click="toggleFilter">
          {{ clients.query.active ? '仅活跃设备' : '全部设备' }}
        </el-button>
      </div>
      <div class="cl__chips">
        <span v-for="c in chips" :key="c.label" class="cl__chip">
          {{ c.label }}<b class="gw-num">{{ c.value }}</b>
        </span>
      </div>
    </div>

    <div class="gw-card cl__table">
      <el-table :data="clients.rows" v-loading="clients.loading" size="small" row-key="ip">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="cl__detail">
              <div v-if="row.recent.length">
                <div class="gw-muted cl__detail-title">最近查询(新→旧)</div>
                <div class="cl__domains gw-num">{{ row.recent.slice(0, CLIENT_VIEW.RECENT).join('  ·  ') }}</div>
              </div>
              <div>
                <div class="gw-muted cl__detail-title">记录类型</div>
                <el-tag v-for="(n, t) in row.types" :key="t" size="small" type="info" class="cl__type">
                  {{ t }} × {{ n }}
                </el-tag>
                <span v-if="!Object.keys(row.types).length" class="gw-muted">面板启动后没有查到这个设备的 DNS 请求</span>
              </div>
              <div class="gw-muted cl__note">
                首次观测于 {{ fmtTime(row.firstSeen) }}；DNS 计数从面板启动开始累计，重启后清零。
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="ip" label="IP" width="140">
          <template #default="{ row }">
            <span class="gw-num">{{ row.ip }}</span>
            <el-tag v-if="row.active" size="small" type="success" effect="plain" class="cl__live">活跃</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="hostname" label="主机名" min-width="130">
          <template #default="{ row }">{{ row.hostname || '—' }}</template>
        </el-table-column>
        <el-table-column prop="mac" label="MAC" width="160">
          <template #default="{ row }"><span class="gw-num">{{ row.mac || '—' }}</span></template>
        </el-table-column>
        <el-table-column prop="dev" label="接口" width="90">
          <template #default="{ row }">{{ row.dev || '—' }}</template>
        </el-table-column>
        <el-table-column label="链路" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.neighState" size="small" :type="stateTag(row.neighState)">{{ row.neighState }}</el-tag>
            <span v-else class="gw-muted">仅 DNS</span>
          </template>
        </el-table-column>
        <el-table-column label="DNS 查询" width="100" align="right" sortable :sort-by="(r) => r.queries">
          <template #default="{ row }"><span class="gw-num">{{ row.queries }}</span></template>
        </el-table-column>
        <el-table-column label="隧道 / 直连" width="120" align="right">
          <template #default="{ row }">
            <span class="gw-num cl__proxy">{{ row.proxy }}</span>
            <span class="gw-muted"> / </span>
            <span class="gw-num cl__direct">{{ row.direct }}</span>
          </template>
        </el-table-column>
        <el-table-column label="最近请求" min-width="150">
          <template #default="{ row }">
            <span v-if="row.lastQuery" class="gw-num">{{ fmtTime(row.lastQuery, 'HH:mm:ss') }}
              <em class="cl__idle gw-muted">({{ fmtDuration(row.idle) }}前)</em>
            </span>
            <span v-else class="gw-muted">无记录</span>
          </template>
        </el-table-column>
        <template #empty><span class="gw-muted">还没有观测到设备：客户端的网关/DNS 指向本机后会自动出现在这里。</span></template>
      </el-table>
      <el-pagination class="cl__page" layout="total, sizes, prev, pager, next" background
                     :total="clients.total" v-model:current-page="clients.query.pageNum"
                     v-model:page-size="clients.query.pageSize" :page-sizes="PAGINATION.PAGE_SIZES"
                     @current-change="clients.fetchList()" @size-change="clients.fetchList()" />
    </div>
  </div>
</template>

<style scoped>
.cl__toolbar {
  display: flex; flex-direction: column; gap: 10px; padding: 12px 14px; margin-bottom: 12px;
}
.cl__filters { flex-wrap: wrap; }
.cl__kw { width: 260px; }
.cl__chips { display: flex; flex-wrap: wrap; gap: 8px; }
.cl__chip {
  font-size: 12px; color: var(--gw-text-2); padding: 3px 10px; border-radius: 999px;
  background: var(--gw-bg-soft); border: 1px solid var(--gw-border-soft);
}
.cl__chip b { margin-left: 6px; color: var(--gw-text-1); }
.cl__table { padding: 4px 10px 10px; }
.cl__live { margin-left: 6px; }
.cl__page { margin-top: 10px; justify-content: flex-end; }
.cl__detail { display: flex; flex-direction: column; gap: 10px; padding: 10px 16px; }
.cl__detail-title { font-size: 12px; margin-bottom: 4px; }
.cl__domains { word-break: break-all; font-size: 12px; color: var(--gw-text-1); }
.cl__type { margin-right: 6px; }
.cl__note { font-size: 12px; }
.cl__idle { font-style: normal; font-size: 12px; margin-left: 4px; }
.cl__proxy { color: var(--gw-accent); }
.cl__direct { color: var(--gw-success); }
</style>
