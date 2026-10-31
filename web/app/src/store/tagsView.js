// 职责: 顶部多标签页状态。affix(仪表盘)固定不可关。
import { defineStore } from 'pinia'
import { ref } from 'vue'
import router from '@/router'

export const useTagsViewStore = defineStore('tagsView', () => {
  const visited = ref([]) // {path,title,affix}

  function add(route) {
    if (route.path === '/' || route.meta?.hidden || !route.meta?.title) return
    if (!visited.value.find((v) => v.path === route.path))
      visited.value.push({ path: route.path, title: route.meta.title, affix: !!route.meta.affix })
  }
  function remove(path) {
    const i = visited.value.findIndex((v) => v.path === path)
    if (i < 0 || visited.value[i].affix) return
    visited.value.splice(i, 1)
    if (router.currentRoute.value.path === path)
      router.push(visited.value[Math.max(0, i - 1)]?.path || '/dashboard')
  }
  function closeOthers(path) {
    visited.value = visited.value.filter((v) => v.affix || v.path === path)
    if (router.currentRoute.value.path !== path) router.push(path)
  }
  function clear() {
    visited.value = visited.value.filter((v) => v.affix)
    router.push('/dashboard')
  }

  // 初始化固定标签
  router.getRoutes().forEach((r) => {
    if (r.meta?.affix) visited.value.push({ path: r.path, title: r.meta.title, affix: true })
  })

  return { visited, add, remove, closeOthers, clear }
})
