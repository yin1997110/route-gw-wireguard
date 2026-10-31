// 职责: DNS 观测接口——分流配置概览 / 分上游解析对比 / 规则命中流水。全部只读。
import request from './request'

export const getDnsOverview = () => request.get('/dns/overview')
export const queryDns = (params) => request.get('/dns/query', { params })
export const getDnsHits = (params) => request.get('/dns/hits', { params })

// EXTENSION_POINT: DNS 黑名单/自定义域名下发等写接口在此追加