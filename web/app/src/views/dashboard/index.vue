<!-- 职责: 仪表盘页。实时速率/流量/当前节点/资源占用 + 时序曲线。业务数据全部来自 system store。 -->
<script setup>
import { computed, onActivated, onDeactivated } from 'vue'
import { useSystemStore } from '@/store/system'
import SpeedChart from '@/components/SpeedChart.vue'
import DelayBadge from '@/components/DelayBadge.vue'
import StatusTag from '@/components/StatusTag.vue'
import { fmtBytes, fmtSpeed, fmtDuration } from '@/utils/format'

const sys = useSystemStore()

const cards = computed(() => [
  { key: 'up', label: '实时上行', value: fmtSpeed(sys.live.up), sub: `峰值 ${fmtSpeed(sys.overviewMeta.peakUp || 0)}`, icon: 'Top', color: 'var(--gw-success)' },
  { key: 'down', label: '实时下行', value: fmtSpeed(sys.live.down), sub: `峰值 ${fmtSpeed(sys.overviewMeta.peakDown || 0)}`, icon: 'Bottom', color: 'var(--gw-accent)' },
  { key: 'today', label: '今日流量', value: fmtBytes((sys.overviewMeta.todayUp || 0) + (sys.overviewMeta.todayDown || 0)), sub: `↑${fmtBytes(sys.overviewMeta.todayUp || 0)} ↓${fmtBytes(sys.overviewMeta.todayDown || 0)}`, icon: 'Calendar', color: 'var(--gw-warning)' },
  { key: 'month', label: '本月流量', value: fmtBytes((sys.overviewMeta.monthUp || 0) + (sys.overviewMeta.monthDown || 0)), sub: `↑${fmtBytes(sys.overviewMeta.monthUp || 0)} ↓${fmtBytes(sys.overviewMeta.monthDown || 0)}`, icon: 'DataAnalysis', color: 'var(--gw-info)' }
])

// keep-alive 下用激活钩子，离开页面即停掉实时轮询
onActivated(() => { sys.fetchOverview(); sys.startRealtime() })
onDeactivated(() => sys.stopRealtime())
</script>

<template>
  <div class="gw-page db">
    <!-- 指标卡 -->
    <el-row :gutter="12">
      <el-col v-for="c in cards" :key="c.key" :xs="12" :sm="12" :md="6">
        <div class="gw-card gw-card--hover db__card">
          <div class="db__icon" :style="{ '--tone': c.color }"><el-icon :size="18"><component :is="c.icon" /></el-icon></div>
          <div>
            <div class="db__label">{{ c.label }}</div>
            <div class="db__value gw-num">{{ c.value }}</div>
            <div class="gw-muted">{{ c.sub }}</div>
          </div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="12" class="gw-mb" style="margin-top: 12px">
      <!-- 时序曲线 -->
      <el-col :xs="24" :md="16">
        <div class="gw-card db__chart">
          <div class="gw-flex gw-flex--between gw-mb">
            <span class="gw-card__title">实时吞吐</span>
            <span class="gw-muted">每 2s 采样 · 滚动窗口</span>
          </div>
          <SpeedChart :points="sys.points" />
        </div>
      </el-col>

      <!-- 当前节点 + 资源 -->
      <el-col :xs="24" :md="8">
        <div class="gw-card db__node">
          <span class="gw-card__title gw-mb">当前节点</span>
          <template v-if="sys.overview">
            <div class="db__node-head">
              <span class="db__flag">{{ sys.overview.flag }}</span>
              <div>
                <div class="db__node-name">{{ sys.overview.name }}</div>
                <div class="gw-muted">{{ sys.overview.country }} · {{ sys.overview.city }} · {{ sys.overview.group }}</div>
              </div>
              <StatusTag :status="sys.overview.status" class="db__node-tag" />
            </div>
            <ul class="db__kv">
              <li><span>隧道延迟</span><DelayBadge :delay="sys.live.latency" /></li>
              <li><span>运行时长</span><b class="gw-num">{{ fmtDuration(sys.overview.uptime) }}</b></li>
              <li><span>隧道出口</span><b class="gw-num">{{ sys.overview.exitIp || '—' }}</b></li>
            </ul>
            <div class="db__res">
              <div class="db__res-item">
                <span class="gw-muted">CPU</span>
                <el-progress :percentage="Math.round(sys.live.cpu)" :stroke-width="6" striped />
              </div>
              <div class="db__res-item">
                <span class="gw-muted">内存</span>
                <el-progress :percentage="Math.round(sys.live.mem)" :stroke-width="6" striped
                             :color="(p) => (p > 85 ? 'var(--gw-danger)' : 'var(--gw-accent)')" />
              </div>
            </div>
          </template>
          <el-skeleton v-else :rows="4" animated />
        </div>
      </el-col>
    </el-row>
    <!-- EXTENSION_POINT: 分流命中 Top 域名、按设备明细卡片在此追加 -->
  </div>
</template>

<style scoped>
.db__card { display: flex; gap: 12px; align-items: center; padding: 16px; margin-bottom: 12px; }
.db__icon {
  width: 42px; height: 42px; border-radius: var(--gw-radius-md); flex-shrink: 0;
  display: grid; place-items: center; color: var(--tone);
  background: color-mix(in srgb, var(--tone) 14%, transparent);
  border: 1px solid color-mix(in srgb, var(--tone) 30%, transparent);
}
.db__label { font-size: 12px; color: var(--gw-text-2); }
.db__value { font-size: 20px; font-weight: 700; line-height: 1.35; }
.db__chart, .db__node { padding: 16px; min-height: 330px; }
.db__node-head { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }
.db__flag { font-size: 26px; }
.db__node-name { font-weight: 600; }
.db__node-tag { margin-left: auto; }
.db__kv { list-style: none; margin: 0 0 14px; padding: 0; }
.db__kv li {
  display: flex; justify-content: space-between; padding: 7px 0;
  border-bottom: 1px dashed var(--gw-border-soft); color: var(--gw-text-2); font-size: 13px;
}
.db__kv b { color: var(--gw-text-1); font-weight: 600; }
.db__res { display: flex; flex-direction: column; gap: 10px; }
.db__res-item span { display: block; margin-bottom: 4px; }
</style>
