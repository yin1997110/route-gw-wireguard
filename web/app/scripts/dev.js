// 职责: `npm run dev` 启动器——同时拉起 Mock 后端与 Vite，零额外依赖
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const run = (cmd, args) => {
  const p = spawn(cmd, args, { cwd: root, stdio: 'inherit', shell: true })
  p.on('exit', (code) => process.exit(code ?? 0))
  return p
}
const mock = run('node', ['server/mock-server.js'])
const web = run('npx', ['vite'])
process.on('exit', () => { mock.kill(); web.kill() })
