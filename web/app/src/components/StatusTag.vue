<!-- 职责: 节点状态标签(公共)。props.status 对齐 constants.NODE_STATUS。 -->
<script setup>
import { computed } from 'vue'
import { NODE_STATUS } from '@/constants/config'

const props = defineProps({ status: { type: String, required: true } })
const meta = computed(() => Object.values(NODE_STATUS).find((s) => s.value === props.status) || NODE_STATUS.OFFLINE)
</script>

<template>
  <el-tag :type="meta.tag" effect="light" round size="small" class="st-tag">
    <span class="st-dot" :class="`st-dot--${meta.tag}`" />
    {{ meta.label }}
  </el-tag>
</template>

<style scoped>
.st-tag { display: inline-flex; align-items: center; gap: 5px; }
.st-dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
.st-dot--success { background: var(--gw-success); animation: st-pulse 1.6s var(--gw-ease) infinite; }
.st-dot--danger { background: var(--gw-danger); }
.st-dot--warning { background: var(--gw-warning); animation: st-pulse 1s linear infinite; }
.st-dot--info { background: var(--gw-info); }
@keyframes st-pulse {
  0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--gw-success) 45%, transparent); }
  50% { box-shadow: 0 0 0 4px transparent; }
}
</style>
