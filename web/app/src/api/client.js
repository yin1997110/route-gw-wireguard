// 职责: 客户端设备观测接口(邻居表 + DNS 查询活跃度)。只读，不下发任何设备策略。
import request from './request'

export const listClient = (params) => request.get('/client/list', { params })

// EXTENSION_POINT: 设备限速/绑定静态 ARP 等写接口在此追加