<!-- 职责: 自动切换与自愈设置页。探测参数/切换策略表单 + 立即探测 + 最近切换记录。 -->
<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useSystemStore } from '@/store/system'
import { useNodeStore } from '@/store/nodes'
import { PROBE, SWITCH, TRAFFIC } from '@/constants/config'
import { fmtTime } from '@/utils/format'

const sys = useSystemStore()
const nodes = useNodeStore()
const saving = ref(false)
const probing = ref(false)
const form = reactive({
  enabled: true,
  probeType: PROBE.TYPES[0].value,
  interval: PROBE.INTERVAL,
  timeout: PROBE.TIMEOUT,
  failThreshold: PROBE.FAIL_THRESHOLD,
  cooldown: SWITCH.COOLDOWN,
  sameRegionFirst: SWITCH.SAME_REGION_FIRST,
  groups: [],
  resetDay: TRAFFIC.RESET_DAY
})

async function load() {
  await sys.fetchAutoSwitch()
  Object.assign(form, sys.autoSwitch || {})
  if (!form.probeType) form.probeType = PROBE.TYPES[0].value
}
async function submit() {
  saving.value = true
  try { await sys.saveAutoSwitch({ ...form }) } finally { saving.value = false }
}
async function doProbe() {
  probing.value = true
  try {
    await sys.probeNow()
    await sys.fetchSwitchEvents()
    await nodes.fetchList()
  } finally { probing.value = false }
}

onMounted(() => { load(); nodes.fetchList(); sys.fetchSwitchEvents() })
// EXTENSION_POINT: 通知渠道(钉钉/邮件/Bark)、探测源节点选择在此扩展
</script>

<template>
  <div class="gw-page as">
    <div class="as__grid">
      <div class="gw-card as__form">
        <div class="gw-card__title">探测与健康检查</div>
        <el-form :model="form" label-width="120px" label-position="left">
          <el-form-item label="启用自愈">
            <el-switch v-model="form.enabled" />
            <span class="gw-muted as__tip">{{ form.enabled ? '故障节点将被自动剔除并切换' : '仅记录状态，不做任何切换' }}</span>
          </el-form-item>
          <el-form-item label="探测方式">
            <el-radio-group v-model="form.probeType">
              <el-radio-button v-for="t in PROBE.TYPES" :key="t.value" :value="t.value">{{ t.label }}</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="探测间隔">
            <el-input-number v-model="form.interval" :min="5" :max="600" :step="5" />
            <span class="gw-muted as__tip">秒</span>
          </el-form-item>
          <el-form-item label="单次超时">
            <el-input-number v-model="form.timeout" :min="1" :max="30" />
            <span class="gw-muted as__tip">秒</span>
          </el-form-item>
          <el-form-item label="故障判定阈值">
            <el-input-number v-model="form.failThreshold" :min="1" :max="10" />
            <span class="gw-muted as__tip">连续失败次数</span>
          </el-form-item>
        </el-form>
      </div>

      <div class="gw-card as__form">
        <div class="gw-card__title">切换策略</div>
        <el-form :model="form" label-width="120px" label-position="left">
          <el-form-item label="切换冷却">
            <el-input-number v-model="form.cooldown" :min="30" :max="3600" :step="30" />
            <span class="gw-muted as__tip">秒，冷却期内不再重复切换</span>
          </el-form-item>
          <el-form-item label="同区域优先">
            <el-switch v-model="form.sameRegionFirst" />
            <span class="gw-muted as__tip">优先挑选与原节点同国家/城市的备选</span>
          </el-form-item>
          <el-form-item label="监控分组">
            <el-select v-model="form.groups" multiple class="as__fill" placeholder="留空 = 纳入全部 WG 分组">
              <el-option v-for="g in nodes.groups" :key="g" :label="g" :value="g" />
            </el-select>
            <span class="gw-muted as__tip">{{ form.groups.length ? '仅在这些分组内挑选备选节点' : '未选择分组：自愈可在全部 WG 分组内挑选' }}</span>
          </el-form-item>
          <el-form-item label="流量重置日">
            <el-input-number v-model="form.resetDay" :min="1" :max="28" />
            <span class="gw-muted as__tip">每月第几号重新统计月度流量</span>
          </el-form-item>
        </el-form>
        <div class="gw-flex gw-flex--gap as__actions">
          <el-button type="primary" :loading="saving" @click="submit">保存并生效</el-button>
          <el-button :loading="probing" icon="Aim" @click="doProbe">立即探测全部节点</el-button>
          <el-button link @click="load">还原未保存修改</el-button>
        </div>
      </div>
    </div>

    <div class="gw-card as__events">
      <div class="gw-card__title">最近自动切换</div>
      <el-table :data="sys.switchEvents" size="small">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ fmtTime(row.time) }}</template>
        </el-table-column>
        <el-table-column prop="from" label="原节点" min-width="140" />
        <el-table-column prop="to" label="切换到" min-width="140" />
        <el-table-column prop="reason" label="原因" min-width="180" />
        <template #empty><span class="gw-muted">暂无自动切换记录</span></template>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.as__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 12px; }
.as__form { padding: 14px 16px; }
.as__tip { margin-left: 10px; font-size: 12px; }
.as__fill { width: 100%; }
.as__actions { margin-top: 6px; }
.as__events { margin-top: 12px; padding: 14px 16px; }

@media (max-width: 768px) {
  .as__grid { grid-template-columns: 1fr; }
}
</style>
