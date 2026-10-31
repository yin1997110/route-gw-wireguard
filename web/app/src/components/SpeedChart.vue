<!-- 职责: 上下行速率时序图(公共)。ECharts 封装，颜色全部读取 CSS 变量，主题切换自动重绘。
     props.points: [{t(ms), up(B/s), down(B/s)}] -->
<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import dayjs from 'dayjs'
import { useSettingsStore } from '@/store/settings'

const props = defineProps({
  points: { type: Array, default: () => [] },
  height: { type: String, default: '260px' }
})

const el = ref(null)
let chart = null
const settings = useSettingsStore()

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

function buildOption() {
  const accent = cssVar('--gw-accent')
  return {
    animation: false,
    grid: { left: 8, right: 8, top: 30, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v) => `${(v / 1024).toFixed(1)} KB/s`,
      backgroundColor: cssVar('--gw-popup'),
      borderColor: cssVar('--gw-border'),
      textStyle: { color: cssVar('--gw-text-1'), fontSize: 12 }
    },
    legend: {
      data: ['下行', '上行'], right: 0, top: 0,
      textStyle: { color: cssVar('--gw-text-2') }, icon: 'roundRect', itemWidth: 10, itemHeight: 4
    },
    xAxis: {
      type: 'category', boundaryGap: false,
      data: props.points.map((p) => dayjs(p.t).format('HH:mm:ss')),
      axisLine: { lineStyle: { color: cssVar('--gw-chart-grid') } },
      axisLabel: { color: cssVar('--gw-text-3'), fontSize: 10 }
    },
    yAxis: {
      type: 'value', splitLine: { lineStyle: { color: cssVar('--gw-chart-grid') } },
      axisLabel: {
        color: cssVar('--gw-text-3'), fontSize: 10,
        formatter: (v) => (v >= 1048576 ? `${(v / 1048576).toFixed(1)}M` : `${(v / 1024).toFixed(0)}K`)
      }
    },
    series: [
      // EXTENSION_POINT: series 可配置化(增加协议维度等)从这里扩展
      mk('下行', 'down', accent),
      mk('上行', 'up', cssVar('--gw-success'))
    ]
  }
}
function mk(name, key, color) {
  return {
    name, type: 'line', smooth: 0.4, showSymbol: false,
    data: props.points.map((p) => p[key]),
    lineStyle: { width: 1.6, color },
    areaStyle: {
      color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: color + '55' }, { offset: 1, color: color + '00' }
      ])
    }
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
  <div ref="el" class="sc" :style="{ height }" />
</template>

<style scoped>
.sc { width: 100%; }
</style>
