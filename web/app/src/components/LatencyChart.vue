<!-- 职责: 隧道延迟时序图(公共)。与 SpeedChart 同一套 ECharts 封装与主题取色方式，
     数据来自"每次实测 ping"的采样点，不是 2s 轮询插值。
     props.points: [{t(ms), ms|null, loss(0~1)}]；props.warn: 超过该毫秒数画一条告警线 -->
<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import dayjs from 'dayjs'
import { useSettingsStore } from '@/store/settings'

const props = defineProps({
  points: { type: Array, default: () => [] },
  height: { type: String, default: '220px' },
  warn: { type: Number, default: null }
})

const el = ref(null)
let chart = null
const settings = useSettingsStore()

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function buildOption() {
  const accent = cssVar('--gw-accent')
  const warn = cssVar('--gw-warning')
  return {
    animation: false,
    grid: { left: 8, right: 8, top: 30, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      formatter: (ps) => {
        const p = ps[0]
        const it = props.points[p.dataIndex] || {}
        const ms = it.ms == null ? '超时' : `${it.ms} ms`
        return `${p.axisValue}<br/>延迟 ${ms}${it.loss ? ` · 丢包 ${Math.round(it.loss * 100)}%` : ''}`
      },
      backgroundColor: cssVar('--gw-popup'),
      borderColor: cssVar('--gw-border'),
      textStyle: { color: cssVar('--gw-text-1'), fontSize: 12 }
    },
    legend: {
      data: ['隧道延迟'], right: 0, top: 0,
      textStyle: { color: cssVar('--gw-text-2') }, icon: 'roundRect', itemWidth: 10, itemHeight: 4
    },
    xAxis: {
      type: 'category', boundaryGap: false,
      data: props.points.map((p) => dayjs(p.t).format('HH:mm:ss')),
      axisLine: { lineStyle: { color: cssVar('--gw-chart-grid') } },
      axisLabel: { color: cssVar('--gw-text-3'), fontSize: 10 }
    },
    yAxis: {
      type: 'value', name: 'ms', nameTextStyle: { color: cssVar('--gw-text-3'), fontSize: 10 },
      splitLine: { lineStyle: { color: cssVar('--gw-chart-grid') } },
      axisLabel: { color: cssVar('--gw-text-3'), fontSize: 10 }
    },
    series: [{
      name: '隧道延迟', type: 'line', smooth: 0.4, showSymbol: false, connectNulls: false,
      data: props.points.map((p) => p.ms),
      lineStyle: { width: 1.6, color: accent },
      itemStyle: { color: accent },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: accent + '55' }, { offset: 1, color: accent + '00' }
        ])
      },
      // 丢包点单独标出来：延迟曲线断掉的地方往往就是隧道出问题的时刻
      markPoint: {
        symbolSize: 34, itemStyle: { color: cssVar('--gw-danger') },
        label: { color: cssVar('--gw-text-1'), fontSize: 9 },
        data: props.points
          .map((p, i) => (p.loss ? { coord: [i, p.ms ?? 0], value: '丢', xAxis: p.t } : null))
          .filter(Boolean)
      },
      ...(props.warn ? {
        markLine: {
          symbol: 'none', silent: true,
          lineStyle: { color: warn, type: 'dashed', width: 1 },
          label: { color: warn, fontSize: 10, formatter: `慢阈值 ${props.warn}ms` },
          data: [{ yAxis: props.warn }]
        }
      } : {})
    }]
  }
}

function render() { if (chart) chart.setOption(buildOption(), true) }
const onResize = () => chart?.resize()

onMounted(() => {
  chart = echarts.init(el.value)
  render()
  window.addEventListener('resize', onResize)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose(); chart = null
})
watch(() => props.points, render, { deep: false })
watch(() => [settings.mode, settings.accent], () => render())
</script>

<template>
  <div ref="el" class="lc" :style="{ height }" />
</template>

<style scoped>
.lc { width: 100%; }
</style>
