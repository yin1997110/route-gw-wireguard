<!-- 职责: 侧栏。Logo + 由路由表生成的菜单；高亮当前路由，折叠时只显示图标。 -->
<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '@/store/app'
import { APP } from '@/constants/config'

const route = useRoute()
const router = useRouter()
const app = useAppStore()

const menus = computed(() =>
  router.getRoutes()
    .filter((r) => r.meta?.title && !r.meta.hidden && r.path !== '/')
    .map((r) => ({ path: r.path, ...r.meta }))
    .sort((a, b) => a.path.localeCompare(b.path))
)
// 保持菜单顺序与路由表定义一致(而非字典序)
const order = computed(() =>
  router.options.routes.flatMap((r) => (r.children || []).map((c) => '/' + c.path))
)
const sortedMenus = computed(() =>
  [...menus.value].sort((a, b) => order.value.indexOf(a.path) - order.value.indexOf(b.path))
)

function go(path) {
  router.push(path)
  app.closeMobileDrawer()
}
</script>

<template>
  <div class="sb">
    <div class="sb__logo" :class="{ 'sb__logo--mini': app.sidebarCollapsed && !app.isMobile }">
      <span class="sb__logo-mark">◢◤</span>
      <span v-show="!app.sidebarCollapsed || app.isMobile" class="sb__logo-text">{{ APP.NAME }}</span>
    </div>
    <el-menu :default-active="route.path" :collapse="app.sidebarCollapsed && !app.isMobile"
             class="sb__menu">
      <el-menu-item v-for="m in sortedMenus" :key="m.path" :index="m.path" @click="go(m.path)">
        <el-icon><component :is="m.icon" /></el-icon>
        <template #title>{{ m.title }}</template>
      </el-menu-item>
    </el-menu>
    <div v-show="!app.sidebarCollapsed || app.isMobile" class="sb__foot gw-muted">v1.0 · self-hosted</div>
  </div>
</template>

<style scoped>
.sb { display: flex; flex-direction: column; height: 100%; }
.sb__logo {
  height: var(--gw-header-h); display: flex; align-items: center; gap: 8px;
  padding: 0 16px; flex-shrink: 0; white-space: nowrap; overflow: hidden;
}
.sb__logo--mini { padding: 0 12px; }
.sb__logo-mark {
  color: var(--gw-accent); font-weight: 700; font-size: 16px;
  text-shadow: 0 0 12px var(--gw-accent-line);
}
.sb__logo-text { font-weight: 700; letter-spacing: 2px; color: var(--gw-text-1); }
.sb__menu { flex: 1; border-right: none; }
.sb__menu :deep(.el-menu-item) {
  margin: 4px 8px; border-radius: var(--gw-radius-sm);
  transition: background var(--gw-dur-fast) var(--gw-ease);
}
.sb__menu :deep(.el-menu-item.is-active) {
  background: var(--gw-accent-soft);
  color: var(--gw-text-1);
  box-shadow: inset 2px 0 0 var(--gw-accent);
}
.sb__foot { padding: 12px 16px; }
</style>
