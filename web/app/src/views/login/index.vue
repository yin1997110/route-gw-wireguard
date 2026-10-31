<!-- 职责: 登录页。账号密码鉴权入口(会话为后端 HttpOnly Cookie)；回车提交，失败由 request 层统一提示。 -->
<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/store/auth'
import { AUTH, APP } from '@/constants/config'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const formRef = ref()
const form = reactive({ username: '', password: '' })
const loading = ref(false)

// 表单校验规则常量：长度下限取自 AUTH，避免页面散落魔法数
const rules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, min: AUTH.MIN_PASSWORD, message: `密码至少 ${AUTH.MIN_PASSWORD} 位`, trigger: 'blur' }]
}

async function submit() {
  if (loading.value || !(await formRef.value.validate().catch(() => false))) return
  loading.value = true
  try {
    await auth.login({ ...form })
    router.replace(route.query.redirect || AUTH.USER_HOME)
  } catch { /* 失败提示由 request 层统一弹出，这里只负责结束提交态 */ }
  finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="lg">
    <div class="lg__bg" aria-hidden="true" />
    <section class="lg__box gw-card">
      <header class="lg__head">
        <span class="lg__mark">◢◤</span>
        <h1 class="lg__title">{{ APP.NAME }}</h1>
        <p class="gw-muted lg__sub">管理面板 · 需登录后访问</p>
      </header>

      <el-form ref="formRef" :model="form" :rules="rules" size="large" @submit.prevent="submit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="账号" autocomplete="username" clearable
                    prefix-icon="User" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" placeholder="密码" autocomplete="current-password"
                    show-password prefix-icon="Lock" @keyup.enter="submit" />
        </el-form-item>
        <el-button class="lg__submit" type="primary" :loading="loading" native-type="submit" size="large"
                   @click="submit">
          登 录
        </el-button>
      </el-form>

      <p class="gw-muted lg__tip">
        首次部署的初始密码在服务器 <span class="gw-num">data/INITIAL_PASSWORD.txt</span>，登录后请尽快在系统设置中修改。
      </p>
      <!-- EXTENSION_POINT: 双因子 / 登录验证码在此扩展 -->
    </section>
    <footer class="gw-muted lg__foot">{{ APP.NAME }} · self-hosted</footer>
  </div>
</template>

<style scoped>
.lg {
  position: relative; display: flex; flex-direction: column;
  align-items: center; justify-content: center; height: 100%;
  padding: 24px 16px; overflow: hidden;
}
/* 背景光晕：色值全部来自 token，页内不写死颜色 */
.lg__bg {
  position: absolute; inset: -30% -10% auto; height: 70%;
  background: radial-gradient(60% 60% at 50% 0%, var(--gw-accent-soft), transparent 70%);
  pointer-events: none;
}
.lg__box {
  position: relative; width: var(--gw-login-w); max-width: 100%;
  box-shadow: var(--gw-login-glow);
  animation: lg-in var(--gw-dur-slow) var(--gw-ease-out) both;
}
@keyframes lg-in {
  from { opacity: 0; transform: translateY(14px) scale(0.98); }
  to { opacity: 1; transform: none; }
}
.lg__head { text-align: center; margin-bottom: 18px; }
.lg__mark {
  display: inline-block; color: var(--gw-accent); font-weight: 700; font-size: 22px;
  text-shadow: 0 0 16px var(--gw-accent-line);
}
.lg__title {
  margin: 6px 0 2px; font-size: 18px; font-weight: 700;
  letter-spacing: 3px; color: var(--gw-text-1);
}
.lg__sub { letter-spacing: 1px; }
.lg__submit { width: 100%; margin-top: 4px; letter-spacing: 6px; }
.lg__tip { margin: 14px 0 0; line-height: 1.6; text-align: center; }
.lg__foot { position: absolute; bottom: 14px; }
</style>
