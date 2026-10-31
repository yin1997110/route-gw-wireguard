<!-- 职责: 系统设置页。网关操作(重载/重启/备份/恢复)、网关基础配置、账号安全、运行环境与隧道自检。 -->
<script setup>
import { ref, reactive, computed, onActivated } from 'vue'
import { ElMessage } from 'element-plus'
import { useSystemStore } from '@/store/system'
import { useAuthStore } from '@/store/auth'
import { APP, AUTH } from '@/constants/config'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import StatusTag from '@/components/StatusTag.vue'
import DelayBadge from '@/components/DelayBadge.vue'
import { fmtTime } from '@/utils/format'

const sys = useSystemStore()
const auth = useAuthStore()
const op = reactive({ reload: false, restart: false })

async function doReload() {
  op.reload = true
  try { await sys.reload() } finally { op.reload = false }
}
async function doRestart() {
  op.restart = true
  try { await sys.restart() } finally { op.restart = false }
}

// ---- 备份 / 恢复 ----
async function onBackup() {
  const data = await sys.backup()
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `gw-backup-${new Date().toISOString().slice(0, 10)}.json`
  a.click(); URL.revokeObjectURL(a.href)
  ElMessage.success('备份文件已下载')
}
const fileRef = ref()
const pending = ref(null)
const confirmRestore = reactive({ open: false, name: '' })
async function onFile(e) {
  const f = e.target.files?.[0]
  if (!f) return
  try {
    // 选中文件只解析、不写入：恢复会覆盖全部配置，必须再过一次确认
    pending.value = JSON.parse(await f.text())
    confirmRestore.name = f.name
    confirmRestore.open = true
  } catch { ElMessage.error('备份文件解析失败') }
  e.target.value = ''
}
async function doRestore() {
  if (!pending.value) return
  await sys.restore(pending.value)
  pending.value = null
  await Promise.all([sys.fetchConfig(), sys.fetchSysInfo()])
}

// ---- 网关配置 ----
const cfgForm = ref({})
// 单臂旁路由：网关地址与 DNS 地址是同一个（默认路由网卡上的本机地址）
const lanAddr = computed(() =>
  cfgForm.value.lanIp ? `${cfgForm.value.lanIp}/${cfgForm.value.lanPrefix || ''}` : '—'
)
async function loadConfig() {
  await sys.fetchConfig()
  cfgForm.value = { ...sys.config }
}
async function saveConfig() {
  await sys.saveConfig({ ...cfgForm.value })
}

const confirmRestart = reactive({ open: false })

// ---- 账号安全 ----
const pwdRef = ref()
const pwd = reactive({ oldPassword: '', newPassword: '', confirmPassword: '' })
const pwdRules = {
  oldPassword: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  newPassword: [{ required: true, min: AUTH.MIN_PASSWORD, message: `至少 ${AUTH.MIN_PASSWORD} 位`, trigger: 'blur' }],
  confirmPassword: [{
    required: true,
    validator: (r, v, cb) => (v === pwd.newPassword ? cb() : cb(new Error('两次输入的新密码不一致'))),
    trigger: 'blur'
  }]
}
const savingPwd = ref(false)
async function savePwd() {
  if (!(await pwdRef.value.validate().catch(() => false))) return
  savingPwd.value = true
  try {
    await auth.changePassword({ oldPassword: pwd.oldPassword, newPassword: pwd.newPassword })
    pwdRef.value.resetFields()
  } finally { savingPwd.value = false }
}

// 会话为 Cookie，改密不会踢掉当前会话；返回本页时重新拉取状态与隧道自检
onActivated(() => { loadConfig(); sys.fetchSysInfo(); sys.fetchTunnel() })
// EXTENSION_POINT: 更多网关操作(清除路由缓存、重启 dnsmasq、数据源立即更新)在此扩展为独立操作卡
</script>

<template>
  <div class="gw-page st">
    <div class="st__grid">
      <div class="gw-card st__ops">
        <div class="gw-card__title">网关操作</div>
        <div class="st__oplist">
          <div class="st__op">
            <div>
              <div class="st__opname">重载配置</div>
              <div class="gw-muted st__opdesc">重新读取规则与数据源，不中断现有隧道</div>
            </div>
            <el-button :loading="op.reload" icon="Refresh" @click="doReload">执行</el-button>
          </div>
          <div class="st__op">
            <div>
              <div class="st__opname">重启网关</div>
              <div class="gw-muted st__opdesc">WireGuard 隧道重建，全网中断约 2~5 秒</div>
            </div>
            <el-button type="warning" plain :loading="op.restart" icon="SwitchButton" @click="confirmRestart.open = true">重启</el-button>
          </div>
          <div class="st__op">
            <div>
              <div class="st__opname">导出备份</div>
              <div class="gw-muted st__opdesc">节点 / 规则 / 订阅 / 自动切换配置打包为 JSON</div>
            </div>
            <el-button icon="Download" @click="onBackup">下载</el-button>
          </div>
          <div class="st__op">
            <div>
              <div class="st__opname">恢复备份</div>
              <div class="gw-muted st__opdesc">将覆盖当前全部配置，操作前建议先导出现状</div>
            </div>
            <el-button icon="Upload" @click="fileRef.click()">选择文件</el-button>
            <input ref="fileRef" type="file" accept="application/json" hidden @change="onFile" />
          </div>
        </div>
      </div>

      <div class="gw-card st__cfg">
        <div class="gw-card__title">旁路由接入</div>
        <template v-if="sys.config">
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="接入模式">同网段旁路由（单网卡 · 网关与 DNS 同地址）</el-descriptions-item>
            <el-descriptions-item label="本机地址">{{ lanAddr }}</el-descriptions-item>
            <el-descriptions-item label="内网网段">{{ cfgForm.lanCidr || '—' }}</el-descriptions-item>
            <el-descriptions-item label="上游网关">{{ cfgForm.wanGw || '—' }}（{{ cfgForm.wanIf || '—' }}）</el-descriptions-item>
            <el-descriptions-item label="客户端填法">
              网关 = <b class="gw-num">{{ cfgForm.lanIp || '—' }}</b>，DNS = <b class="gw-num">{{ cfgForm.lanIp || '—' }}</b>
            </el-descriptions-item>
          </el-descriptions>
          <div class="st__bypass-tip">
            同网段任意主机把「默认网关」和「DNS」都指向本机即可分流：国内直连、其余走隧道。
            地址或网络变化后本页自动跟随，不用改代码或配置。
          </div>
          <el-form :model="cfgForm" label-width="110px" label-position="left">
            <el-form-item label="WG 隧道地址">
              <span class="gw-num">{{ cfgForm.wgLan || '—' }}</span>
              <span class="gw-muted st__opdesc">（wg0，自动读取）</span>
            </el-form-item>
            <el-form-item label="MSS 钳制"><el-switch v-model="cfgForm.mssClamp" /></el-form-item>
            <el-form-item label="国内路由数">
              <span class="gw-num">{{ cfgForm.chinaRouteCount }}</span>
              <span class="gw-muted st__opdesc">条 · 数据源每日 {{ cfgForm.listUpdateAt }} 自动更新</span>
            </el-form-item>
            <el-form-item label="分流域名数">
              <span class="gw-num">{{ cfgForm.gfwDomainCount }}</span>
              <span class="gw-muted st__opdesc">条 · 由 gfwlist 同步</span>
            </el-form-item>
            <div class="gw-flex st__cfg-actions">
              <el-button type="primary" @click="saveConfig">保存</el-button>
              <el-button link @click="loadConfig">放弃修改</el-button>
            </div>
          </el-form>
        </template>
        <el-skeleton v-else :rows="5" animated />
      </div>

      <div class="gw-card st__pwd">
        <div class="gw-card__title">账号安全</div>
        <div class="gw-muted st__opdesc st__pwd-tip">当前账号 <span class="gw-num">{{ auth.username }}</span> · 会话有效期 7 天，改密后下次登录生效</div>
        <el-form ref="pwdRef" :model="pwd" :rules="pwdRules" label-width="80px" label-position="top">
          <el-form-item label="原密码" prop="oldPassword">
            <el-input v-model="pwd.oldPassword" type="password" show-password autocomplete="current-password" />
          </el-form-item>
          <el-form-item label="新密码" prop="newPassword">
            <el-input v-model="pwd.newPassword" type="password" show-password autocomplete="new-password" />
          </el-form-item>
          <el-form-item label="确认新密码" prop="confirmPassword">
            <el-input v-model="pwd.confirmPassword" type="password" show-password autocomplete="new-password" />
          </el-form-item>
          <el-button type="primary" :loading="savingPwd" @click="savePwd">修改密码</el-button>
        </el-form>
      </div>
    </div>

    <div class="gw-card st__info">
      <div class="gw-card__title">运行环境</div>
      <el-descriptions v-if="sys.sysInfo" :column="3" border size="small">
        <el-descriptions-item label="面板版本">{{ APP.VERSION }}</el-descriptions-item>
        <el-descriptions-item label="主机">{{ sys.sysInfo.hostname }}</el-descriptions-item>
        <el-descriptions-item label="系统">{{ sys.sysInfo.os }}</el-descriptions-item>
        <el-descriptions-item label="内核">{{ sys.sysInfo.kernel }}</el-descriptions-item>
        <el-descriptions-item label="CPU">{{ sys.sysInfo.cpu }}</el-descriptions-item>
        <el-descriptions-item label="内存">{{ sys.sysInfo.memUsed }} / {{ sys.sysInfo.memTotal }}</el-descriptions-item>
        <el-descriptions-item label="运行时长">{{ sys.sysInfo.uptime }}</el-descriptions-item>
        <el-descriptions-item label="负载">{{ sys.sysInfo.loadAvg }}</el-descriptions-item>
        <el-descriptions-item label="网关地址">{{ sys.sysInfo.gatewayIp }}</el-descriptions-item>
        <el-descriptions-item label="DNS 服务">{{ sys.sysInfo.dnsMode }}</el-descriptions-item>
        <el-descriptions-item label="数据源更新">{{ fmtTime(sys.sysInfo.listUpdatedAt) }}</el-descriptions-item>
        <el-descriptions-item label="最近启动">{{ fmtTime(sys.sysInfo.bootAt) }}</el-descriptions-item>
      </el-descriptions>
      <el-skeleton v-else :rows="3" animated />
    </div>

    <div class="gw-card st__info">
      <div class="gw-flex gw-flex--between st__head">
        <div class="gw-card__title">隧道自检</div>
        <el-button link type="primary" icon="Refresh" @click="sys.fetchTunnel()">重新检测</el-button>
      </div>
      <el-descriptions v-if="sys.tunnel" :column="3" border size="small">
        <el-descriptions-item label="wg0">
          <StatusTag :status="sys.tunnel.wgUp ? 'online' : 'offline'" />
        </el-descriptions-item>
        <el-descriptions-item label="对端入口">{{ sys.tunnel.peer?.endpoint || '—' }}</el-descriptions-item>
        <el-descriptions-item label="最近握手">{{ fmtTime((sys.tunnel.peer?.handshake || 0) * 1000) }}</el-descriptions-item>
        <el-descriptions-item label="隧道延迟">
          <DelayBadge :delay="sys.tunnel.latency" :loss="sys.tunnel.loss" />
        </el-descriptions-item>
        <el-descriptions-item label="出口 IP">{{ sys.tunnel.exitIp || '—' }}</el-descriptions-item>
        <el-descriptions-item label="监听端口">{{ sys.tunnel.listen || '—' }}</el-descriptions-item>
        <el-descriptions-item label="策略路由">{{ sys.tunnel.rules?.length || 0 }} 条</el-descriptions-item>
        <el-descriptions-item label="明细/隧道表">{{ sys.tunnel.mainRoutes }} / {{ sys.tunnel.tableRoutes }}</el-descriptions-item>
        <el-descriptions-item label="查询日志">{{ sys.tunnel.queryLog ? '已开启' : '已关闭' }}</el-descriptions-item>
        <el-descriptions-item label="命中统计">{{ sys.tunnel.hitsTracked }} 条</el-descriptions-item>
        <el-descriptions-item label="自愈">{{ sys.tunnel.autoswitch?.enabled ? '启用' : '停用' }}</el-descriptions-item>
        <el-descriptions-item label="最近切换">{{ fmtTime((sys.tunnel.lastSwitch || 0) * 1000) }}</el-descriptions-item>
      </el-descriptions>
      <el-skeleton v-else :rows="3" animated />
    </div>

    <ConfirmDialog v-model="confirmRestart.open" title="重启网关" danger
                   text="重启会重建 WireGuard 隧道，下挂所有设备的网络将中断数秒。"
                   @confirm="doRestart(); confirmRestart.open = false" />
    <ConfirmDialog v-model="confirmRestore.open" title="恢复备份" danger
                   :text="`将用「${confirmRestore.name}」覆盖当前全部配置(手动节点/规则/订阅/自动切换/网关参数)，不可撤销。`"
                   @confirm="doRestore(); confirmRestore.open = false" />
  </div>
</template>

<style scoped>
.st__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 12px; }
.st__ops, .st__cfg, .st__pwd { padding: 14px 16px; }
.st__oplist { display: flex; flex-direction: column; gap: 4px; }
.st__op {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 8px; border-radius: var(--gw-radius-sm);
  transition: background var(--gw-dur-fast) var(--gw-ease);
}
.st__op:hover { background: var(--gw-card-hover); }
.st__op + .st__op { border-top: 1px solid var(--gw-border-soft); }
.st__opname { font-size: 14px; font-weight: 600; }
.st__opdesc { font-size: 12px; margin-top: 2px; }
.st__cfg-actions { margin-top: 8px; }
.st__bypass-tip {
  margin: 10px 0 4px; padding: 8px 10px; font-size: 12px; line-height: 1.7;
  color: var(--gw-text-2); background: var(--gw-card-hover);
  border-left: 3px solid var(--gw-accent); border-radius: var(--gw-radius-sm);
}
.st__info { margin-top: 12px; padding: 14px 16px; }
.st__info > .gw-card__title, .st__head { margin-bottom: 10px; }
.st__pwd-tip { display: block; margin-bottom: 10px; }

@media (max-width: 768px) {
  .st__grid { grid-template-columns: 1fr; }
}
</style>
