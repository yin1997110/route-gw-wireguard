// 职责: 登录鉴权接口。会话是后端下发的 HttpOnly Cookie，前端不持有 token、不落本地存储。
// EXTENSION_POINT: 二次验证 / 验证码接口在此追加
import request from './request'

export const login = (data) => request.post('/login', data)
export const logout = () => request.post('/logout')
// 会话探测：静默(401 属正常分支，不弹错、由路由守卫跳转登录页)
export const getUserInfo = () => request.get('/user/info', { silent: true })
export const changePassword = (data) => request.post('/system/password', data)
