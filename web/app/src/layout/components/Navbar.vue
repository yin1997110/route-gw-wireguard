<!-- 职责: 顶栏。折叠按钮 + 面包屑 + 当前节点速览 + 账号菜单 + 主题抽屉入口。 -->
<script setup>
import { onMounted, onUnmounted, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '@/store/app'
import { useAuthStore } from '@/store/auth'
import { useNodeStore } from '@/store/nodes'
import { AUTH } from '@/constants/config'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import DelayBadge from '@/components/DelayBadge.vue'
import ThemeDrawerTrigger from './ThemeDrawerTrigger.vue'

const app = useAppStore()
const route = useRoute()
const router = useRouter()
const nodes = useNodeStore()
const auth = useAuthStore()
const askLogout = reactive({ open: false })

function onCommand(cmd) {
  if (cmd === 'password') router.push(AUTH.PASSWORD_PAGE)
  else if (cmd === 'logout') askLogout.open = true
}

// 登出：断开后端会话后回登录页；节点轮询随布局卸载(onUnmounted)一并停止
async function doLogout() {
  askLogout.open = false
  await auth.logout()
  router.replace(AUTH.LOGIN_PATH)
}
// 顶栏常驻显示当前节点，布局存活期间持有全局唯一的节点轮询
onMounted(() => { nodes.fetchList(); nodes.startPoll() })
onUnmounted(() => nodes.stopPoll())
</script>

<template>
  <div class="nb gw-flex gw-flex--between">
    <div class="gw-flex gw-flex--gap">
      <el-icon class="nb__btn" :size="18" @click="app.toggleSidebar()">
        <Fold v-if="!app.sidebarCollapsed || app.isMobile" /><Expand v-else />
      </el-icon>
      <el-breadcrumb separator="/">
        <el-breadcrumb-item>{{ route.meta?.title }}</el-breadcrumb-item>
      </el-breadcrumb>
    </div>
    <div class="gw-flex gw-flex--gap">
      <div v-if="nodes.current" class="nb__node gw-muted">
        <span class="nb__node-dot" />
        {{ nodes.current.name }}
        <DelayBadge :delay="nodes.current.delay" :loss="nodes.current.loss" />
      </div>
      <ThemeDrawerTrigger />
      <el-dropdown trigger="click" @command="onCommand">
        <div class="nb__user">
          <el-icon :size="15"><UserFilled /></el-icon>
          <span class="nb__name">{{ auth.username }}</span>
          <el-icon :size="12"><ArrowDown /></el-icon>
        </div>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="password" icon="Key">修改密码</el-dropdown-item>
            <el-dropdown-item command="logout" icon="SwitchButton" divided>退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <!-- EXTENSION_POINT: 全屏 / 消息中心在此追加 -->
    </div>
    <ConfirmDialog v-model="askLogout.open" title="退出登录"
                   text="退出后需重新输入账号密码才能进入面板，网关分流不受影响。"
                   @confirm="doLogout" />
  </div>
</template>

<style scoped>
.nb { height: 100%; padding: 0 14px; }
.nb__btn { cursor: pointer; color: var(--gw-text-2); transition: color var(--gw-dur-fast); }
.nb__btn:hover { color: var(--gw-accent); }
.nb__node {
  display: flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 999px;
  background: var(--gw-accent-soft); border: 1px solid var(--gw-accent-line);
  font-size: 12px; color: var(--gw-text-1);
}
.nb__node-dot {
  width: 6px; height: 6px; border-radius: 50%; background: var(--gw-success);
  box-shadow: 0 0 6px var(--gw-success);
}
.nb__user {
  display: flex; align-items: center; gap: 6px; cursor: pointer; outline: none;
  padding: 4px 10px; border-radius: 999px; color: var(--gw-text-2);
  border: 1px solid var(--gw-border-soft); background: var(--gw-card);
  transition: color var(--gw-dur-fast) var(--gw-ease), border-color var(--gw-dur-fast) var(--gw-ease),
              background var(--gw-dur-fast) var(--gw-ease);
}
.nb__user:hover {
  color: var(--gw-text-1); border-color: var(--gw-accent-line); background: var(--gw-card-hover);
}
.nb__name { font-size: 12px; max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
