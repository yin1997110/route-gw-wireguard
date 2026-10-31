// 职责: 布局全局状态——侧栏折叠、移动端设备检测。
import { defineStore } from 'pinia'
import { ref, onMounted, onUnmounted } from 'vue'
import { LAYOUT } from '@/constants/config'

const MOBILE = LAYOUT.MOBILE_BP

export const useAppStore = defineStore('app', () => {
  const sidebarCollapsed = ref(window.innerWidth <= MOBILE)
  const isMobile = ref(window.innerWidth <= MOBILE)
  const mobileDrawer = ref(false) // 移动端侧栏抽屉

  function toggleSidebar() {
    if (isMobile.value) mobileDrawer.value = !mobileDrawer.value
    else sidebarCollapsed.value = !sidebarCollapsed.value
  }
  function closeMobileDrawer() { mobileDrawer.value = false }

  const onResize = () => {
    const m = window.innerWidth <= MOBILE
    if (m !== isMobile.value) { isMobile.value = m; mobileDrawer.value = false }
  }
  onMounted(() => window.addEventListener('resize', onResize))
  onUnmounted(() => window.removeEventListener('resize', onResize))

  return { sidebarCollapsed, isMobile, mobileDrawer, toggleSidebar, closeMobileDrawer }
})
