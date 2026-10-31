// 职责: 分流规则接口
import request from './request'

export const listRuleGroup = () => request.get('/rule/group')
export const addRuleGroup = (data) => request.post('/rule/group', data)
export const delRuleGroup = (id) => request.delete(`/rule/group/${id}`)
export const listRule = (params) => request.get('/rule/list', { params })
export const addRule = (data) => request.post('/rule', data)
export const updateRule = (data) => request.put('/rule', data)
export const delRule = (ids) => request.delete(`/rule/${ids.join(',')}`)
export const reorderRule = (data) => request.put('/rule/reorder', data)
export const listRuleHit = (params) => request.get('/rule/hits', { params })
