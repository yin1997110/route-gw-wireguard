<!-- 职责: 危险操作确认弹窗(公共)。v-model 显隐，confirm 事件由父级控制 loading。 -->
<script setup>
defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '确认操作' },
  text: { type: String, default: '确定执行该操作？' },
  danger: { type: Boolean, default: false },
  loading: { type: Boolean, default: false }
})
const emit = defineEmits(['update:modelValue', 'confirm'])
function close() { emit('update:modelValue', false) }
</script>

<template>
  <el-dialog :model-value="modelValue" :title="title" width="min(420px, 92vw)" align-center
             @update:model-value="close" @closed="close">
    <div class="cd-text">{{ text }}</div>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button :type="danger ? 'danger' : 'primary'" :loading="loading" @click="emit('confirm')">
        确认执行
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.cd-text { color: var(--gw-text-2); line-height: 1.7; }
</style>
