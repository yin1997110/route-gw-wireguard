// 职责: 事件日志接口
import request from './request'

export const listEvent = (params) => request.get('/event/list', { params })
export const clearEvent = () => request.delete('/event')
// 切换历史：由事件流按"发起 → 结果"配对而来，只读，不改事件存储
export const listSwitchHistory = (params) => request.get('/switch/history', { params })
