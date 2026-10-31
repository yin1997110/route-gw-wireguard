<!-- 职责: 主题抽屉触发按钮(与 Drawer 状态同在 settings 域)。 -->
<script setup>
import { ref } from 'vue'
import ThemeDrawer from './ThemeDrawer.vue'

const open = ref(false)
</script>

<template>
  <el-icon class="td-btn" :size="18" @click="open = true"><Brush /></el-icon>
  <ThemeDrawer v-model="open" />
</template>

<style scoped>
.td-btn { cursor: pointer; color: var(--gw-text-2); transition: color var(--gw-dur-fast), transform var(--gw-dur); }
.td-btn:hover { color: var(--gw-accent); transform: rotate(-15deg); }
</style>
