<!-- 职责: 日志查看器。只读展示白名单日志源(dnsmasq/隧道/面板/数据源脚本)的最近若干行。 -->
<script setup>
import { computed, onMounted, onDeactivated } from 'vue'
import { useLogStore } from '@/store/logs'
import { LOGS } from '@/constants/config'
import { fmtTime } from '@/utils/format'

const lg = useLogStore()

const unitState = (u) => (u.kind === 'journal'
  ? (u.active ? { label: '运行中', tag: 'success' } : { label: '未运行', tag: 'info' })
  : (u.active === 'active' ? { label: '文件存在', tag: 'success' } : { label: '文件缺失', tag: 'warning' }))
const picked = computed(() => lg.units.find((u) => u.key === lg.query.unit) || null)

function changeUnit() { lg.query.keyword = ''; lg.resetPage() }
function search() { lg.fetchLogs() }

onMounted(async () => { await lg.fetchUnits(); lg.fetchLogs() })
// 离开页面务必停掉跟随：journalctl 每次都要 fork 进程，1 核机器上不能让它空转
onDeactivated(() => lg.setFollow(false))
// EXTENSION_POINT: 按时间范围筛选、日志下载在此扩展
</script>

<template>
  <div class="gw-page lv">
    <div class="gw-card lv__toolbar">
      <div class="gw-flex gw-flex--gap">
        <el-select v-model="lg.query.unit" class="lv__sel" @change="changeUnit">
          <el-option v-for="u in lg.units" :key="u.key" :label="u.label" :value="u.key">
            <span>{{ u.label }}</span>
            <el-tag class="lv__opt-tag" size="small" :type="unitState(u).tag" effect="plain">{{ unitState(u).label }}</el-tag>
          </el-option>
        </el-select>
        <el-select v-model="lg.query.lines" class="lv__num" @change="search">
          <el-option v-for="n in LOGS.LINES" :key="n" :label="`最近 ${n} 行`" :value="n" />
        </el-select>
        <el-input v-model="lg.query.keyword" placeholder="过滤关键字" clearable class="lv__kw"
                  @keyup.enter="search" @clear="search" />
        <el-button type="primary" icon="Search" @click="search">查询</el-button>
      </div>
      <div class="gw-flex gw-flex--gap">
        <el-tooltip content="跟随刷新每 15s 拉取一次，关闭可省资源" placement="bottom">
          <el-switch v-model="lg.follow" active-text="跟随" @change="lg.setFollow(lg.follow)" />
        </el-tooltip>
        <el-button plain icon="Refresh" :loading="lg.loading" @click="lg.fetchLogs()">刷新</el-button>
      </div>
    </div>

    <div class="gw-card lv__body" v-loading="lg.loading">
      <div class="lv__meta">
        <span class="gw-card__title">{{ lg.meta.label || '日志' }}</span>
        <span class="lv__src gw-num">{{ lg.meta.source || '—' }}</span>
        <span class="gw-muted">读取 {{ lg.meta.scanned ?? 0 }} 行 · 命中 {{ lg.meta.matched ?? 0 }} 行</span>
      </div>
      <el-alert v-if="picked && picked.kind === 'file' && picked.active !== 'active'" type="warning"
                :closable="false" show-icon title="该日志文件当前不存在，通常是脚本尚未运行过或日志已轮转。" />
      <div class="lv__lines gw-num">
        <div v-for="(l, i) in lg.rows" :key="i" class="lv__line" :title="l.head">
          <span class="lv__t">{{ l.t ? fmtTime(l.t, 'HH:mm:ss') : '—' }}</span>
          <span class="lv__text">{{ l.text }}</span>
        </div>
        <div v-if="!lg.rows.length && !lg.loading" class="gw-muted lv__empty">没有匹配的日志行</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.lv__toolbar {
  display: flex; flex-wrap: wrap; gap: 10px; justify-content: space-between; align-items: center;
  padding: 12px 14px; margin-bottom: 12px;
}
.lv__sel { width: 190px; }
.lv__num { width: 130px; }
.lv__kw { width: 200px; }
.lv__opt-tag { float: right; margin-top: 3px; }
.lv__body { padding: 14px 16px; }
.lv__meta { display: flex; flex-wrap: wrap; gap: 14px; align-items: baseline; margin-bottom: 12px; }
.lv__src { font-size: 12px; color: var(--gw-text-2); }
.lv__lines {
  max-height: 62vh; overflow: auto; margin-top: 10px; padding: 10px 12px;
  background: var(--gw-bg-soft); border: 1px solid var(--gw-border-soft); border-radius: var(--gw-radius-sm);
  font-size: 12px; line-height: 1.7;
}
.lv__line { display: flex; gap: 8px; white-space: pre-wrap; word-break: break-all; }
.lv__line:hover { background: color-mix(in srgb, var(--gw-accent) 8%, transparent); }
.lv__t { color: var(--gw-text-3); flex-shrink: 0; }
.lv__text { color: var(--gw-text-1); }
.lv__empty { padding: 18px; text-align: center; }
</style>
