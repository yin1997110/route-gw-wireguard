// 职责: 路由表 = 菜单。新页面在 appRoutes.children 追加一项 + 建 views 目录即可。
// 鉴权：白名单外的路由先确认会话(/user/info)，未登录一律带 redirect 跳登录页。
// EXTENSION_POINT: 后续面板（DNS 管理、终端设备、协议明细等）在此注册。
import { createRouter, createWebHashHistory } from 'vue-router'
import Layout from '@/layout/index.vue'
import { AUTH } from '@/constants/config'
import { useAuthStore } from '@/store/auth'

const appRoutes = [
  {
    path: AUTH.LOGIN_PATH,
    name: 'Login',
    component: () => import('@/views/login/index.vue'),
    meta: { title: '登录', hidden: true }
  },
  {
    path: '/',
    component: Layout,
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/index.vue'),
        meta: { title: '仪表盘', icon: 'Odometer', affix: true }
      },
      {
        path: 'nodes',
        name: 'NodeList',
        component: () => import('@/views/nodes/NodeList.vue'),
        meta: { title: '节点管理', icon: 'Connection' }
      },
      {
        path: 'rules',
        name: 'RuleManage',
        component: () => import('@/views/rules/RuleManage.vue'),
        meta: { title: '分流规则', icon: 'SetUp' }
      },
      {
        path: 'autoswitch',
        name: 'AutoSwitchSetting',
        component: () => import('@/views/autoswitch/AutoSwitchSetting.vue'),
        meta: { title: '自动切换', icon: 'Switch' }
      },
      {
        path: 'dns',
        name: 'DnsManage',
        component: () => import('@/views/dns/DnsManage.vue'),
        meta: { title: 'DNS 管理', icon: 'Position' }
      },
      {
        path: 'clients',
        name: 'ClientList',
        component: () => import('@/views/clients/ClientList.vue'),
        meta: { title: '终端设备', icon: 'Monitor' }
      },
      {
        path: 'lists',
        name: 'DataSource',
        component: () => import('@/views/lists/DataSource.vue'),
        meta: { title: '数据源', icon: 'Files' }
      },
      {
        path: 'switchlog',
        name: 'SwitchHistory',
        component: () => import('@/views/switchlog/SwitchHistory.vue'),
        meta: { title: '切换历史', icon: 'Sort' }
      },
      {
        path: 'logs',
        name: 'LogViewer',
        component: () => import('@/views/logs/LogViewer.vue'),
        meta: { title: '日志查看', icon: 'Notebook' }
      },
      {
        path: 'events',
        name: 'EventLog',
        component: () => import('@/views/events/EventLog.vue'),
        meta: { title: '事件日志', icon: 'Document' }
      },
      {
        path: 'system',
        name: 'SystemSetting',
        component: () => import('@/views/system/SystemSetting.vue'),
        meta: { title: '系统设置', icon: 'Setting' }
      }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' }
]

const router = createRouter({
  history: createWebHashHistory(),
  routes: appRoutes,
  scrollBehavior: () => ({ top: 0 })
})

// 会话确认只在首次进入受保护路由时发生一次；此后由 request 层的 401 兜底跳回登录页
router.beforeEach(async (to) => {
  if (AUTH.WHITE_LIST.includes(to.path)) return true
  const auth = useAuthStore()
  if (!auth.loaded) {
    try { await auth.fetchInfo() } catch { return { path: AUTH.LOGIN_PATH, query: { redirect: to.fullPath } } }
  }
  return auth.loaded ? true : { path: AUTH.LOGIN_PATH, query: { redirect: to.fullPath } }
})

export default router
