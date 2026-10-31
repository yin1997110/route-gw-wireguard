<!-- 职责: 右上角主题设置抽屉。模式切换 + 强调色预设；写入统一走 settings store。
     EXTENSION_POINT: 密度/圆角/字号等新 token 在此追加表单项并同步 settings.applyTheme。 -->
<script setup>
import { useSettingsStore } from '@/store/settings'
import { THEME } from '@/constants/config'

defineProps({ modelValue: Boolean })
const emit = defineEmits(['update:modelValue'])
const settings = useSettingsStore()
</script>

<template>
  <el-drawer :model-value="modelValue" title="主题设置" size="min(300px, 86vw)"
             @update:model-value="emit('update:modelValue', $event)">
    <div class="th-sec">
      <div class="th-label">主题模式</div>
      <el-radio-group v-model="settings.mode">
        <el-radio-button v-for="m in THEME.MODES" :key="m.value" :value="m.value">{{ m.label }}</el-radio-button>
      </el-radio-group>
    </div>
    <div class="th-sec">
      <div class="th-label">强调色</div>
      <div class="th-swatches">
        <button v-for="a in THEME.ACCENTS" :key="a.value" class="th-sw" :title="a.name"
                :class="{ 'th-sw--on': settings.accent === a.value }"
                :style="{ background: a.value }"
                @click="settings.accent = a.value" />
      </div>
    </div>
    <div class="th-sec">
      <div class="th-label">预览</div>
      <div class="th-preview gw-card">
        <el-button type="primary">主要按钮</el-button>
        <el-button>默认</el-button>
        <div class="th-preview-bar"><i /></div>
      </div>
    </div>
  </el-drawer>
</template>

<style scoped>
.th-sec { margin-bottom: 22px; }
.th-label { font-size: 13px; color: var(--gw-text-2); margin-bottom: 10px; }
.th-swatches { display: flex; gap: 10px; }
.th-sw {
  width: 30px; height: 30px; border-radius: 50%; border: 2px solid transparent;
  cursor: pointer; transition: transform var(--gw-dur) var(--gw-ease-out),
  border-color var(--gw-dur-fast);
}
.th-sw:hover { transform: scale(1.12); }
.th-sw--on { border-color: var(--gw-text-1); }
.th-preview { padding: 14px; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.th-preview-bar { width: 100%; height: 6px; border-radius: 3px; overflow: hidden; background: var(--gw-border); }
.th-preview-bar i {
  display: block; height: 100%; width: 62%;
  background: linear-gradient(90deg, var(--gw-accent), color-mix(in srgb, var(--gw-accent) 40%, var(--gw-success)));
}
</style>
