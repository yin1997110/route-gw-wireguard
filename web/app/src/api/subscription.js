// 职责: 订阅管理接口
import request from './request'

export const listSub = () => request.get('/subscription/list')
export const fetchSub = (id) => request.post(`/subscription/fetch/${id}`)
export const addSub = (data) => request.post('/subscription', data)
export const delSub = (id) => request.delete(`/subscription/${id}`)
