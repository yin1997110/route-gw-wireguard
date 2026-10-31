// 职责: 订阅管理接口
import request from './request'

export const listSub = () => request.get('/subscription/list')
export const fetchSub = (id) => request.post(`/subscription/fetch/${id}`)
export const addSub = (data) => request.post('/subscription', data)
export const delSub = (id) => request.delete(`/subscription/${id}`)
// 分流数据源(国内 IP 明细 / gfwlist / 更新脚本与定时任务)状态，及"跑一次既有更新脚本"
export const getListStatus = () => request.get('/list/status')
export const updateLists = () => request.post('/list/update')
