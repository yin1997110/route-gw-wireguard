// 职责: 仪表盘接口
import request from './request'

export const getOverview = () => request.get('/dashboard/overview')
export const getRealtime = () => request.get('/dashboard/realtime')
export const getLatency = () => request.get('/dashboard/latency')
