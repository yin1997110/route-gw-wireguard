// 职责: 系统设置 / 自动切换 / 备份恢复接口
import request from './request'

export const getSysInfo = () => request.get('/system/info')
export const getTunnel = () => request.get('/system/tunnel')
export const reloadGw = () => request.post('/system/reload')
export const restartGw = () => request.post('/system/restart')
export const getBackup = () => request.get('/system/backup')
export const restoreBackup = (data) => request.post('/system/restore', data)
export const getConfig = () => request.get('/system/config')
export const putConfig = (data) => request.put('/system/config', data)
export const testSource = (url) => request.post('/system/source/test', { url })
export const getAutoSwitch = () => request.get('/system/autoswitch')
export const putAutoSwitch = (data) => request.put('/system/autoswitch', data)
export const probeNow = () => request.post('/system/probe-now')
// 日志查看器：只允许读后端白名单里的日志源
export const getLogUnits = () => request.get('/system/log-units')
export const getLogs = (params) => request.get('/system/logs', { params })
