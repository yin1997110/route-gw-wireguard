// 职责: 纯函数格式化。新格式化函数一律加在这里，禁止写进组件。
import dayjs from 'dayjs'

/** 字节 → KB/MB/GB/TB */
export function fmtBytes(n, digits = 1) {
  if (n == null || Number.isNaN(+n)) return '—'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0, v = +n
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(i === 0 || v >= 100 ? 0 : digits)}${u[i]}`
}

/** 字节/秒 → 速率文本 */
export function fmtSpeed(bytesPerSec) {
  return `${fmtBytes(bytesPerSec)}/s`
}

/** 秒 → 运行时长 3d 04:12 */
export function fmtDuration(sec) {
  if (sec == null) return '—'
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return (d ? `${d}d ` : '') + `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

export function fmtTime(ts, pattern = 'MM-DD HH:mm:ss') {
  return ts ? dayjs(ts).format(pattern) : '—'
}
