// 职责: 节点管理接口
import request from './request'

export const listNode = (params) => request.get('/node/list', { params })
export const addNode = (data) => request.post('/node', data)
export const updateNode = (data) => request.put('/node', data)
export const delNode = (ids) => request.delete(`/node/${ids.join(',')}`)
export const switchNode = (id) => request.post(`/node/switch/${id}`)
export const exportNode = () => request.get('/node/export')
export const importNode = (rows) => request.post('/node/import', { rows })
