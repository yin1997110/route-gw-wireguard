// 职责: 鉴权状态。用户身份、登录/登出/改密动作；会话由后端 Cookie 维持，本 store 只做内存镜像。
// loaded 是"已向后端确认过会话"的标记，供路由守卫避免重复请求 /user/info。
// EXTENSION_POINT: 多账号/权限角色(只读账号)在此扩展 roles 与 hasPerm()
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import * as authApi from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const username = ref('')
  const loaded = ref(false)

  async function fetchInfo() {
    const d = await authApi.getUserInfo()
    username.value = d.username
    loaded.value = true
    return d
  }

  async function login(form) {
    const d = await authApi.login(form)
    username.value = d.username
    loaded.value = true
    ElMessage.success(`欢迎回来，${d.username}`)
    return d
  }

  // 登出必须把前端状态清干净：即使后端请求失败也要本地 reset，否则会停在"已登录"假象
  async function logout() {
    try { await authApi.logout() } catch { /* 后端不可达也要放行本地登出 */ }
    reset()
    ElMessage.success('已退出登录')
  }

  async function changePassword(form) {
    await authApi.changePassword(form)
    ElMessage.success('密码已更新，请牢记新密码')
  }

  function reset() {
    username.value = ''
    loaded.value = false
  }

  return { username, loaded, fetchInfo, login, logout, changePassword, reset }
})
