<!-- 职责: DNS 管理页。看 dnsmasq 分流配置与数据文件、按上游对比解析、跟规则命中流水。
     页面只渲染与派发，数据与动作都在 useDnsStore。 -->
<script setup>
import { computed, reactive, onActivated, onDeactivated } from 'vue'
import { useDnsStore } from '@/store/dns'
import { DNS, RULE_ACTIONS } from '@/constants/config'
import { fmtTime } from '@/utils/format'

const dns = useDnsStore()
const detail = reactive({ open: false, row: null })

const metrics = computed(() => {
  const c = dns.overview?.counts || {}
  const s = dns.overview?.service || {}
  return [
    { key: 'svc', label: 'dnsmasq', value: s.active === 'active' ? '运行中' : (s.active || '未知'),
      sub: `${s.enabled || '—'} · ${s.version || '版本未知'}`, tone: s.active === 'active' ? 'var(--gw-success)' : 'var(--gw-danger)' },
    { key: 'qlog', label: '查询日志', value: dns.overview?.queryLog ? '已开启' : '已关闭',
      sub: `命中流水 ${dns.hits.length} 条 · 观测客户端 ${dns.overview?.observed?.clients ?? 0}`,
      tone: dns.overview?.queryLog ? 'var(--gw-accent)' : 'var(--gw-text-3)' },
    { key: 'china', label: '国内 IP 明细', value: `${dns.overview?.counts?.chinaIp ?? '—'} 条`,
      sub: `策略路由数据源(${dns.overview?.listPath || '—'})`, tone: 'var(--gw-warning)' },
    { key: 'gfw', label: '分流域名', value: `${dns.overview?.counts?.gfwDomain ?? '—'} 条`,
      sub: `gfwlist ${dns.overview?.counts?.gfwDomain ?? 0} + 手工 ${dns.overview?.counts?.customDomain ?? 0} + 面板 ${dns.overview?.counts?.panelDomain ?? 0}`,
      tone: 'var(--gw-info)' }
  ]
})

const actionOf = (v) => RULE_ACTIONS.find((a) => a.value === v) || { label: v, tag: 'info' }

function openDetail(row) {
  detail.row = row
  detail.open = true
}

onActivated(() => {
  dns.fetchOverview()
  dns.fetchHits()
  dns.startPoll()
})
onDeactivated(() => dns.stopPoll())
// EXTENSION_POINT: 自定义域名增删(写 98-custom-domain.conf)在此扩展
</script>

<template>
  <div class="gw-page dn">
    <el-row :gutter="12">
      <el-col v-for="m in metrics" :key="m.key" :xs="12" :sm="12" :md="6">
        <div class="gw-card gw-card--hover dn__card">
          <div class="dn__tone" :style="{ '--tone': m.tone }" />
          <div>
            <div class="dn__label">{{ m.label }}</div>
            <div class="dn__value gw-num">{{ m.value }}</div>
            <div class="gw-muted dn__sub">{{ m.sub }}</div>
          </div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="12" style="margin-top: 12px">
      <!-- 解析对比测试 -->
      <el-col :xs="24" :md="14">
        <div class="gw-card dn__panel">
          <div class="gw-flex gw-flex--between gw-mb">
            <span class="gw-card__title">解析对比测试</span>
            <span class="gw-muted">同一域名分别问本机 dnsmasq / 隧道上游 / 直连上游</span>
          </div>
          <div class="gw-flex gw-flex--gap dn__form">
            <el-input v-model="dns.test.domain" placeholder="example.com" class="dn__kw" clearable
                      @keyup.enter="dns.runQuery()" />
            <el-select v-model="dns.test.type" class="dn__sel-sm">
              <el-option v-for="t in DNS.TYPES" :key="t.value" :label="t.label" :value="t.value" />
            </el-select>
            <el-select v-model="dns.test.view" class="dn__sel">
              <el-option v-for="v in DNS.VIEWS" :key="v.value" :label="v.label" :value="v.value" />
            </el-select>
            <el-button type="primary" icon="Position" :loading="dns.testing" @click="dns.runQuery()">解析</el-button>
          </div>

          <el-table v-if="dns.test.results.length" :data="dns.test.results" size="small" class="dn__tbl">
            <el-table-column prop="label" label="视图" width="130" />
            <el-table-column prop="server" label="上游" width="130">
              <template #default="{ row }"><span class="gw-num">{{ row.server }}</span></template>
            </el-table-column>
            <el-table-column label="结论" width="110">
              <template #default="{ row }">
                <el-tag size="small" :type="row.ok && (row.ips.length || row.cname) ? 'success' : row.ok ? 'info' : 'danger'">
                  {{ row.error ? '不可达' : (row.rcode || '—') }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="解析结果" min-width="220">
              <template #default="{ row }">
                <div v-if="row.cname" class="gw-muted">CNAME {{ row.cname }}</div>
                <div v-if="row.ips.length" class="gw-num dn__ips">{{ row.ips.join(' · ') }}</div>
                <span v-if="!row.ips.length && !row.cname" class="gw-muted">
                  {{ row.truncated ? '响应被截断(需 TCP 查询)' : '无记录' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column label="耗时" width="80" align="right">
              <template #default="{ row }"><span class="gw-num">{{ row.ms }}ms</span></template>
            </el-table-column>
          </el-table>
          <div v-else class="gw-muted dn__empty">输入域名后点「解析」，三个上游的返回会并排显示在这里。</div>

          <div v-if="dns.test.matches.length" class="dn__match">
            <span class="gw-muted">命中规则：</span>
            <el-tag v-for="r in dns.test.matches" :key="r.id" size="small" :type="actionOf(r.action).tag" class="dn__match-tag">
              {{ r.pattern }} → {{ actionOf(r.action).label }}
            </el-tag>
          </div>
        </div>
      </el-col>

      <!-- 分流配置来源 -->
      <el-col :xs="24" :md="10">
        <div class="gw-card dn__panel">
          <span class="gw-card__title">分流配置来源</span>
          <ul class="dn__kv">
            <li><span>隧道上游</span><b class="gw-num">{{ dns.overview?.proxyUpstream || '—' }}</b></li>
            <li><span>直连上游</span><b class="gw-num">{{ dns.overview?.directUpstream || '—' }}</b></li>
            <li><span>基础上游</span>
              <b class="gw-num">{{ (dns.overview?.baseUpstreams || []).join(' / ') || '—' }}</b></li>
            <li><span>本机监听</span><b class="gw-num">{{ dns.overview?.local || '—' }}</b></li>
            <li><span>启用规则</span>
              <b class="gw-num">域名 {{ dns.overview?.counts?.ruleDomain ?? 0 }} / IP {{ dns.overview?.counts?.ruleIp ?? 0 }}</b></li>
          </ul>
          <el-table :data="dns.overview?.files || []" size="small" @row-click="openDetail">
            <el-table-column prop="label" label="文件" min-width="150" show-overflow-tooltip />
            <el-table-column label="条目" width="90" align="right">
              <template #default="{ row }">
                <span class="gw-num">{{ row.exists ? (row.serverLines + row.addressLines) : '缺失' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="大小" width="90" align="right">
              <template #default="{ row }"><span class="gw-num">{{ row.bytes || 0 }}</span></template>
            </el-table-column>
            <el-table-column label="更新" width="110" align="right">
              <template #default="{ row }"><span class="gw-num">{{ fmtTime(row.mtime, 'MM-DD HH:mm') }}</span></template>
            </el-table-column>
          </el-table>
          <div class="gw-muted dn__hint">点文件行看路径与明细；改内容请到「分流规则」下发。</div>
        </div>
      </el-col>
    </el-row>

    <!-- 命中流水 -->
    <div class="gw-card dn__panel dn__hits">
      <div class="gw-flex gw-flex--between gw-mb">
        <span class="gw-card__title">规则命中流水</span>
        <span class="gw-muted">每 {{ DNS.HIT_POLL }}s 自动跟随 · 面板启动后的最近 {{ DNS.HIT_LIMIT }} 条</span>
      </div>
      <el-table :data="dns.hits" size="small" max-height="320">
        <el-table-column label="时间" width="150">
          <template #default="{ row }"><span class="gw-num">{{ fmtTime(row.time, 'HH:mm:ss') }}</span></template>
        </el-table-column>
        <el-table-column prop="client" label="客户端" width="150">
          <template #default="{ row }"><span class="gw-num">{{ row.client }}</span></template>
        </el-table-column>
        <el-table-column prop="query" label="域名" min-width="240" show-overflow-tooltip />
        <el-table-column label="动作" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="actionOf(row.action).tag">{{ actionOf(row.action).label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="规则" width="90" align="right">
          <template #default="{ row }"><span class="gw-muted">ID {{ row.ruleId }}</span></template>
        </el-table-column>
        <template #empty>
          <span class="gw-muted">
            还没有命中记录：需要「系统设置」开启查询日志，且在「分流规则」里配置域名规则。
          </span>
        </template>
      </el-table>
    </div>

    <el-dialog v-model="detail.open" :title="detail.row?.label || '文件'" width="min(560px, 92vw)">
      <ul v-if="detail.row" class="dn__kv">
        <li><span>路径</span><b class="gw-num">{{ detail.row.path }}</b></li>
        <li><span>存在</span><b>{{ detail.row.exists ? '是' : '否' }}</b></li>
        <li><span>server= 行</span><b class="gw-num">{{ detail.row.serverLines }}</b></li>
        <li><span>address= 行</span><b class="gw-num">{{ detail.row.addressLines }}</b></li>
        <li><span>有效行</span><b class="gw-num">{{ detail.row.lines }}</b></li>
        <li><span>字节</span><b class="gw-num">{{ detail.row.bytes }}</b></li>
        <li><span>修改时间</span><b class="gw-num">{{ fmtTime(detail.row.mtime) }}</b></li>
      </ul>
    </el-dialog>
  </div>
</template>

<style scoped>
.dn__card { display: flex; gap: 12px; align-items: center; padding: 14px 16px; margin-bottom: 12px; }
.dn__tone { width: 4px; height: 34px; border-radius: 2px; background: var(--tone); flex-shrink: 0; }
.dn__label { font-size: 12px; color: var(--gw-text-2); }
.dn__value { font-size: 18px; font-weight: 700; line-height: 1.4; color: var(--gw-text-1); }
.dn__sub { font-size: 12px; line-height: 1.5; }
.dn__panel { padding: 16px; margin-bottom: 12px; }
.dn__form { flex-wrap: wrap; }
.dn__kw { width: 220px; }
.dn__sel { width: 150px; }
.dn__sel-sm { width: 120px; }
.dn__tbl { margin-top: 12px; }
.dn__ips { word-break: break-all; color: var(--gw-text-1); }
.dn__empty { padding: 18px 0; text-align: center; font-size: 13px; }
.dn__match { margin-top: 10px; font-size: 13px; }
.dn__match-tag { margin-right: 6px; }
.dn__kv { list-style: none; margin: 0 0 12px; padding: 0; }
.dn__kv li {
  display: flex; justify-content: space-between; gap: 10px; padding: 6px 0;
  border-bottom: 1px dashed var(--gw-border-soft); color: var(--gw-text-2); font-size: 13px;
}
.dn__kv b { color: var(--gw-text-1); font-weight: 600; word-break: break-all; }
.dn__hint { margin-top: 8px; font-size: 12px; }
.dn__hits { padding: 16px; }
</style>
