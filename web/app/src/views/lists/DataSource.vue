<!-- 职责: 数据源页。国内 IP 明细/gfwlist/更新脚本与定时任务的状态，以及"手动跑一次既有更新脚本"。 -->
<script setup>
import { computed, ref, onActivated, onDeactivated } from 'vue'
import { useListStore } from '@/store/lists'
import { LIST_VIEW } from '@/constants/config'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import { fmtBytes, fmtTime } from '@/utils/format'

const ls = useListStore()
const updBox = ref(false)

const cards = computed(() => [
  { key: 'china', label: '国内 IP 明细', value: ls.status?.counts?.chinaIp ?? 0, unit: '条',
    sub: '逐条 ip route replace 到主表(直连)', icon: 'Coin', tone: 'var(--gw-accent)' },
  { key: 'gfw', label: '分流域名', value: ls.status?.counts?.gfwDomain ?? 0, unit: '条',
    sub: 'dnsmasq server= 规则', icon: 'Link', tone: 'var(--gw-info)' },
  { key: 'cron', label: '定时更新', value: ls.status?.cronAt || '—', unit: '',
    sub: `下次 ${fmtTime(ls.status?.cronNext, 'MM-DD HH:mm')}`, icon: 'Clock', tone: 'var(--gw-success)' },
  { key: 'matrix', label: '矩阵节点', value: ls.status?.matrix?.total ?? 0, unit: '个',
    sub: `拉取间隔 ${Math.round((ls.status?.matrix?.fetchInterval || 0) / 60)} 分钟`, icon: 'Connection', tone: 'var(--gw-warning)' }
])

async function doUpdate() {
  const r = await ls.runUpdate()
  if (r?.rc === 0) updBox.value = false
}
// keep-alive 下用激活钩子，离开页面即停掉状态轮询
onActivated(() => { ls.fetchStatus(); ls.startPoll() })
onDeactivated(() => ls.stopPoll())
// EXTENSION_POINT: 自定义域名/定时时间写入入口在此扩展(需与网关下发路径对齐后再加)
</script>

<template>
  <div class="gw-page ds">
    <el-row :gutter="12">
      <el-col v-for="c in cards" :key="c.key" :xs="12" :sm="12" :md="6">
        <div class="gw-card gw-card--hover ds__card">
          <div class="ds__icon" :style="{ '--tone': c.tone }"><el-icon :size="18"><component :is="c.icon" /></el-icon></div>
          <div>
            <div class="gw-muted">{{ c.label }}</div>
            <div class="ds__value gw-num">{{ c.value }}<em v-if="c.unit">{{ c.unit }}</em></div>
            <div class="gw-muted ds__sub">{{ c.sub }}</div>
          </div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="12" class="gw-mb" style="margin-top: 12px">
      <el-col :xs="24" :md="14">
        <div class="gw-card ds__panel">
          <div class="gw-flex gw-flex--between gw-mb">
            <span class="gw-card__title">文件清单</span>
            <el-button type="primary" size="small" icon="Refresh"
                       :disabled="!ls.status?.scriptOk" :loading="ls.updating" @click="updBox = true">手动更新</el-button>
          </div>
          <el-alert v-if="ls.status && !ls.status.scriptOk" type="warning" :closable="false" show-icon
                    title="更新脚本不可执行，手动更新已禁用；请检查 /usr/local/bin/update-lists.sh 权限。" class="ds__alert" />
          <el-table :data="ls.status?.files || []" v-loading="ls.loading" size="small">
            <el-table-column prop="label" label="用途" width="150" show-overflow-tooltip />
            <el-table-column prop="path" label="路径" min-width="230" show-overflow-tooltip>
              <template #default="{ row }"><span class="gw-num ds__path">{{ row.path }}</span></template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="row.exists ? 'success' : 'danger'" effect="light">
                  {{ row.exists ? '存在' : '缺失' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="行数" width="90" align="right">
              <template #default="{ row }">
                <span class="gw-num">{{ row.counted ? row.lines : '过大未统计' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="大小" width="90" align="right">
              <template #default="{ row }"><span class="gw-num">{{ fmtBytes(row.bytes) }}</span></template>
            </el-table-column>
            <el-table-column label="更新时间" width="130">
              <template #default="{ row }"><span class="gw-num">{{ row.mtime ? fmtTime(row.mtime) : '—' }}</span></template>
            </el-table-column>
          </el-table>
          <div class="gw-muted ds__note">
            条数只统计非注释行；gfwlist 域名为 dnsmasq <span class="gw-num">server=</span> 计数，手工补充与面板下发单独列出。
          </div>
        </div>
      </el-col>

      <el-col :xs="24" :md="10">
        <div class="gw-card ds__panel">
          <span class="gw-card__title">节点主数据来源</span>
          <ul class="ds__kv">
            <li><span>来源</span><b class="gw-num">{{ ls.status?.matrix?.url || '—' }}</b></li>
            <li><span>节点总数</span><b class="gw-num">{{ ls.status?.matrix?.total ?? 0 }}</b></li>
            <li><span>最近同步</span><b class="gw-num">{{ fmtTime(ls.status?.matrix?.updatedAt) }}</b></li>
            <li><span>矩阵生成时间</span><b class="gw-num">{{ ls.status?.matrix?.builtAt || '—' }}</b></li>
          </ul>
          <span class="gw-card__title ds__sub-title">订阅源</span>
          <el-table :data="ls.status?.subs || []" size="small">
            <el-table-column prop="name" label="名称" min-width="130" show-overflow-tooltip />
            <el-table-column label="节点" width="70" align="right">
              <template #default="{ row }"><span class="gw-num">{{ row.nodeCount ?? 0 }}</span></template>
            </el-table-column>
            <el-table-column label="自动拉取" width="80" align="center">
              <template #default="{ row }">
                <el-tag size="small" :type="row.autoFetch ? 'success' : 'info'" effect="plain">{{ row.autoFetch ? '是' : '否' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="最近拉取" width="110">
              <template #default="{ row }"><span class="gw-num">{{ row.lastFetch ? fmtTime(row.lastFetch) : '—' }}</span></template>
            </el-table-column>
          </el-table>
        </div>
      </el-col>
    </el-row>

    <div class="gw-card ds__panel">
      <div class="gw-flex gw-flex--between gw-mb">
        <span class="gw-card__title">更新日志</span>
        <span class="gw-muted">最近 {{ (ls.status?.logTail || []).length }} 行 · 只读展示 cron 脚本输出</span>
      </div>
      <div class="ds__log gw-num">
        <div v-for="(l, i) in ls.status?.logTail || []" :key="i" class="ds__log-line">{{ l }}</div>
        <div v-if="!(ls.status?.logTail || []).length" class="gw-muted ds__empty">暂无更新日志（脚本尚未运行或日志尚未生成）</div>
      </div>
    </div>

    <ConfirmDialog v-model="updBox" title="手动更新分流数据源"
                   :loading="ls.updating"
                   text="将在网关上执行一次既有的 update-lists.sh（下载国内 IP 明细与 gfwlist 并重建分流配置），耗时约十几秒到两分钟，期间 DNS 解析不受影响。"
                   @confirm="doUpdate" />
  </div>
</template>

<style scoped>
.ds__card { display: flex; gap: 12px; align-items: center; padding: 16px; margin-bottom: 12px; }
.ds__icon {
  width: 42px; height: 42px; border-radius: var(--gw-radius-md); flex-shrink: 0;
  display: grid; place-items: center; color: var(--tone);
  background: color-mix(in srgb, var(--tone) 14%, transparent);
  border: 1px solid color-mix(in srgb, var(--tone) 30%, transparent);
}
.ds__value { font-size: 20px; font-weight: 700; line-height: 1.35; }
.ds__value em { font-style: normal; font-size: 12px; font-weight: 500; margin-left: 3px; color: var(--gw-text-3); }
.ds__sub { font-size: 12px; }
.ds__panel { padding: 16px; margin-bottom: 12px; }
.ds__alert { margin-bottom: 12px; }
.ds__path { font-size: 12px; color: var(--gw-text-2); }
.ds__note { margin-top: 10px; font-size: 12px; line-height: 1.7; }
.ds__kv { list-style: none; margin: 0 0 16px; padding: 0; }
.ds__kv li {
  display: flex; justify-content: space-between; gap: 12px; padding: 7px 0;
  border-bottom: 1px dashed var(--gw-border-soft); color: var(--gw-text-2); font-size: 13px;
}
.ds__kv b { color: var(--gw-text-1); font-weight: 600; text-align: right; word-break: break-all; }
.ds__sub-title { display: block; margin-bottom: 8px; }
.ds__log {
  max-height: 300px; overflow: auto; padding: 10px 12px; font-size: 12px; line-height: 1.7;
  background: var(--gw-bg-soft); border: 1px solid var(--gw-border-soft); border-radius: var(--gw-radius-sm);
}
.ds__log-line { white-space: pre-wrap; word-break: break-all; color: var(--gw-text-1); }
.ds__empty { padding: 16px; text-align: center; }
</style>
