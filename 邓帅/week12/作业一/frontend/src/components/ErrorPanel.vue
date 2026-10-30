<script setup lang="ts">
// 内联错误卡片(功能设计 §6,U3):预览图下方,E1–E4 映射文案 ＋ 两个出口
import { computed } from 'vue'
import { WarningFilled } from '@element-plus/icons-vue'
import type { ApiError } from '../types'

const props = defineProps<{ error: ApiError }>()
defineEmits<{ retry: []; reselect: [] }>()

// E1–E4 文案(功能设计 §7);未知码一律走 E4 兜底
const MESSAGES: Record<string, string> = {
  INVALID_FILE: '仅支持 jpg/png/webp 图片，且不超过 10MB',
  MODEL_TIMEOUT: '识别超时，请重试',
  MODEL_UNPARSABLE: '识别失败，请重试或换一张照片',
  NETWORK: '网络异常，请检查连接后重试',
}

const message = computed(() => MESSAGES[props.error.code] ?? MESSAGES.NETWORK)
</script>

<template>
  <div class="error-panel">
    <div class="error-line">
      <el-icon color="#E6A23C" :size="20"><WarningFilled /></el-icon>
      <span>{{ message }}</span>
    </div>
    <div class="error-actions">
      <el-button type="primary" size="large" @click="$emit('retry')">重试</el-button>
      <el-button size="large" @click="$emit('reselect')">重新选择</el-button>
    </div>
  </div>
</template>

<style scoped>
.error-panel {
  margin-top: 16px;
  padding: 16px;
  border-radius: 8px;
  background: #fdf6ec;
  text-align: center;
}

.error-line {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #b88230;
  font-size: 14px;
}

.error-actions {
  margin-top: 16px;
  display: flex;
  justify-content: center;
  gap: 16px;
}
</style>
