// 职责: 事件日志接口
import request from './request'

export const listEvent = (params) => request.get('/event/list', { params })
export const clearEvent = () => request.delete('/event')
