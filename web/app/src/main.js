// 职责: 应用入口。装配 pinia/router/element-plus(暗色 css-vars)，初始化主题。
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import * as Icons from '@element-plus/icons-vue'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import '@/assets/css/vars.css'
import '@/assets/css/base.css'
import '@/assets/css/element-override.css'

import App from './App.vue'
import router from './router'
import { useSettingsStore } from './store/settings'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
for (const [name, comp] of Object.entries(Icons)) app.component(name, comp)
app.use(ElementPlus, { locale: zhCn })
useSettingsStore(pinia).init() // 主题必须先于挂载应用，避免闪白
app.use(router)
app.mount('#app')
