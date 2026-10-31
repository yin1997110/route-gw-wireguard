// 职责: axios 唯一实例。统一 {code,data,msg} 解包与报错提示；页面禁止直接使用 axios/fetch。
// 会话为后端 Cookie：401 一律清掉前端登录态并跳登录页，业务代码不各自处理。
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { AUTH } from '@/constants/config'
import { useAuthStore } from '@/store/auth'
import router from '@/router'

const service = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 15000
})

// config.silent = true：不弹错(用于 /user/info 这类允许失败的探测请求)
service.interceptors.response.use(
  (res) => {
    const body = res.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 200) return body.data
      // 401 有两种含义：登录页上=账号密码错(要提示)，其他页=会话失效(直接跳登录)
      if (body.code === 401) {
        if (router.currentRoute.value.path === AUTH.LOGIN_PATH) ElMessage.error(body.msg || '账号或密码不正确')
        else toLogin()
      } else if (!res.config?.silent) ElMessage.error(body.msg || '请求失败')
      return Promise.reject(new Error(body.msg || '请求失败'))
    }
    return body
  },
  (err) => {
    if (!err.config?.silent) ElMessage.error(err.message === 'Network Error' ? '无法连接网关服务' : err.message)
    return Promise.reject(err)
  }
)

async function toLogin() {
  useAuthStore().reset()
  if (router.currentRoute.value.path === AUTH.LOGIN_PATH) return
  router.replace({ path: AUTH.LOGIN_PATH, query: { redirect: router.currentRoute.value.fullPath } })
}

export default service
