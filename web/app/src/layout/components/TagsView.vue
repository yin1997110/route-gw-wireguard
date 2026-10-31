<!-- 职责: 顶部多标签页。横向滚动 + 关闭/右键菜单。 -->
<script setup>
import { useRouter } from 'vue-router'
import { useTagsViewStore } from '@/store/tagsView'

const router = useRouter()
const tags = useTagsViewStore()

function ctx(cmd, path) {
  if (cmd === 'close') tags.remove(path)
  if (cmd === 'others') tags.closeOthers(path)
  if (cmd === 'all') tags.clear()
}
</script>

<template>
  <div class="tv">
    <el-scrollbar class="tv__scroll">
      <div class="tv__list">
        <router-link v-for="v in tags.visited" :key="v.path" :to="v.path" custom v-slot="{ navigate, isExactActive }">
          <el-dropdown trigger="contextmenu" @command="(c) => ctx(c, v.path)">
            <span class="tv__item" :class="{ 'tv__item--on': isExactActive }" @click="navigate">
              {{ v.title }}
              <el-icon v-if="!v.affix" class="tv__close"
                       @click.stop.prevent="tags.remove(v.path)"><Close /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="close" :disabled="v.affix">关闭</el-dropdown-item>
                <el-dropdown-item command="others">关闭其他</el-dropdown-item>
                <el-dropdown-item command="all">关闭全部</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </router-link>
      </div>
    </el-scrollbar>
  </div>
</template>

<style scoped>
.tv { height: 100%; padding: 0 10px; }
.tv__list { display: flex; align-items: center; gap: 6px; height: calc(var(--gw-tags-h) - 8px); }
.tv__item {
  display: inline-flex; align-items: center; gap: 5px; cursor: pointer;
  padding: 3px 10px; font-size: 12px; border-radius: var(--gw-radius-sm);
  color: var(--gw-text-2); background: var(--gw-bg-soft);
  border: 1px solid var(--gw-border-soft);
  transition: all var(--gw-dur-fast) var(--gw-ease);
  user-select: none; white-space: nowrap;
}
.tv__item:hover { color: var(--gw-accent); border-color: var(--gw-accent-line); }
.tv__item--on {
  color: var(--gw-accent-contrast); background: var(--gw-accent);
  border-color: var(--gw-accent);
}
.tv__item--on .tv__close { color: var(--gw-accent-contrast); }
.tv__close { border-radius: 50%; transition: background var(--gw-dur-fast); }
.tv__close:hover { background: var(--gw-hover-scrim); }
</style>
