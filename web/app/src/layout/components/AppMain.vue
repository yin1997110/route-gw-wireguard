<!-- 职责: 内容区。路由出口 + 页面切换动画 + keep-alive + 标签联动注册。 -->
<script setup>
import { watch } from 'vue'
import { useRoute } from 'vue-router'
import { useTagsViewStore } from '@/store/tagsView'

const route = useRoute()
const tags = useTagsViewStore()

watch(() => route.path, () => tags.add(route), { immediate: true })
</script>

<template>
  <main class="am">
    <router-view v-slot="{ Component }">
      <transition name="page" mode="out-in">
        <keep-alive :max="6">
          <component :is="Component" :key="route.path" />
        </keep-alive>
      </transition>
    </router-view>
  </main>
</template>

<style scoped>
.am { flex: 1; overflow: auto; background: var(--gw-bg); }
</style>
