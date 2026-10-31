// 职责: 主题设置(模式/强调色)唯一写入口。localStorage 持久化；组件只调 apply*。
// EXTENSION_POINT: 新增 token(密度/圆角/字号)时，在 applyTheme 里挂到 documentElement。
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { THEME } from '@/constants/config'

export const useSettingsStore = defineStore('settings', () => {
  const saved = JSON.parse(localStorage.getItem(THEME.STORAGE_KEY) || '{}')
  const mode = ref(saved.mode || 'dark')
  const accent = ref(saved.accent || THEME.ACCENTS[0].value)

  function applyTheme() {
    const el = document.documentElement
    el.classList.remove('dark', 'light')
    el.classList.add(mode.value)
    el.style.setProperty('--gw-accent', accent.value)
    // 同步 Element Plus 主色梯度(基色取 vars.css 的 --gw-mix-* token)
    el.style.setProperty('--el-color-primary', accent.value)
    for (let i = 1; i <= 9; i++) {
      el.style.setProperty(`--el-color-primary-light-${i}`,
        `color-mix(in srgb, ${accent.value} ${100 - i * 10}%, var(--gw-mix-${mode.value === 'dark' ? 'black' : 'white'}))`)
      el.style.setProperty(`--el-color-primary-dark-${i}`,
        `color-mix(in srgb, ${accent.value} ${100 - i * 10}%, var(--gw-mix-black))`)
    }
  }
  function init() { applyTheme() }
  watch([mode, accent], () => {
    applyTheme()
    localStorage.setItem(THEME.STORAGE_KEY, JSON.stringify({ mode: mode.value, accent: accent.value }))
  })

  return { mode, accent, init, applyTheme }
})
