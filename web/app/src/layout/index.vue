<!-- 职责: 布局壳。侧栏 + 顶栏 + 标签页 + 内容区；移动端侧栏转抽屉。 -->
<script setup>
import { useAppStore } from '@/store/app'
import Sidebar from './components/Sidebar.vue'
import Navbar from './components/Navbar.vue'
import TagsView from './components/TagsView.vue'
import AppMain from './components/AppMain.vue'

const app = useAppStore()
</script>

<template>
  <div class="layout">
    <!-- 桌面端固定侧栏 -->
    <aside v-if="!app.isMobile" class="layout__side"
           :class="{ 'layout__side--collapsed': app.sidebarCollapsed }">
      <Sidebar />
    </aside>
    <!-- 移动端抽屉侧栏 -->
    <el-drawer v-else v-model="app.mobileDrawer" direction="ltr" size="220px"
               :with-header="false" class="layout__drawer">
      <Sidebar />
    </el-drawer>

    <div class="layout__main">
      <header class="layout__header"><Navbar /></header>
      <nav class="layout__tags"><TagsView /></nav>
      <AppMain />
    </div>
  </div>
</template>

<style scoped>
.layout { display: flex; height: 100%; }
.layout__side {
  width: var(--gw-sidebar-w); flex-shrink: 0;
  background: var(--gw-bg-soft);
  border-right: 1px solid var(--gw-border-soft);
  transition: width var(--gw-dur) var(--gw-ease);
  overflow: hidden;
}
.layout__side--collapsed { width: var(--gw-sidebar-w-collapsed); }
.layout__main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.layout__header {
  height: var(--gw-header-h); flex-shrink: 0;
  border-bottom: 1px solid var(--gw-border-soft);
  background: color-mix(in srgb, var(--gw-bg-soft) 80%, transparent);
  backdrop-filter: blur(8px);
}
.layout__tags {
  height: var(--gw-tags-h); flex-shrink: 0;
  border-bottom: 1px solid var(--gw-border-soft);
  background: var(--gw-bg);
}
.layout__drawer :deep(.el-drawer__body) { padding: 0; background: var(--gw-bg-soft); }
</style>
