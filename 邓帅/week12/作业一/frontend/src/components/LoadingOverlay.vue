<script setup lang="ts">
// 识别中遮罩(功能设计 §4,U2):半透明黑底 + spinner + L1 文案
import { Loading } from '@element-plus/icons-vue'

withDefaults(defineProps<{ text?: string }>(), {
  text: '正在识别中…通常 10 秒内出结果',
})
</script>

<template>
  <div class="loading-overlay">
    <el-icon class="is-loading" :size="36" color="#fff"><Loading /></el-icon>
    <p>{{ text }}</p>
  </div>
</template>

<style scoped>
.loading-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background: rgba(0, 0, 0, 0.55);
  border-radius: 8px;
}

p {
  margin: 0;
  color: #fff;
  font-size: 14px;
}
</style>
