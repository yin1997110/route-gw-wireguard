<!-- 职责: 延迟徽章(公共)。按 DELAY.GOOD/BAD 阈值分级着色，颜色来自 CSS 变量。 -->
<script setup>
import { computed } from 'vue'
import { DELAY } from '@/constants/config'

const props = defineProps({
  delay: { type: Number, default: null },
  loss: { type: Number, default: 0 }
})
const level = computed(() => {
  if (props.delay == null) return 'none'
  if (props.loss >= DELAY.LOSS_BAD) return 'bad'
  const slow = props.delay < DELAY.GOOD ? 'good' : props.delay < DELAY.BAD ? 'mid' : 'bad'
  return props.loss >= DELAY.LOSS_MILD && slow === 'good' ? 'mid' : slow
})
const lossText = computed(() => (props.loss >= DELAY.LOSS_MILD ? `${Math.round(props.loss * 100)}%` : ''))
</script>

<template>
  <span class="db gw-num" :class="`db--${level}`">
    <template v-if="delay != null">{{ delay }}ms<em v-if="lossText"> · 丢{{ lossText }}</em></template>
    <template v-else>—</template>
  </span>
</template>

<style scoped>
.db { font-size: 13px; font-weight: 600; }
.db em { font-style: normal; font-weight: 400; font-size: 12px; }
.db--good { color: var(--gw-success); }
.db--mid { color: var(--gw-warning); }
.db--bad { color: var(--gw-danger); }
.db--none { color: var(--gw-text-3); }
</style>
