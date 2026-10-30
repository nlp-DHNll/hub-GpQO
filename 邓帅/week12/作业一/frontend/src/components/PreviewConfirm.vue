<script setup lang="ts">
// 预览确认(功能设计 §3):预览图 + 按钮组;recognizing 覆盖遮罩,error 图下错误卡片
import type { ApiError, ImageSource } from '../types'
import ErrorPanel from './ErrorPanel.vue'
import LoadingOverlay from './LoadingOverlay.vue'

defineProps<{
  previewUrl: string | null
  phase: 'preview' | 'recognizing' | 'error'
  imageSource: ImageSource | null
  error?: ApiError | null
}>()

defineEmits<{
  confirm: []
  retake: []
  cancel: []
  retry: []
  reselect: []
}>()
</script>

<template>
  <div class="preview-confirm">
    <div class="preview-wrap">
      <img v-if="previewUrl" :src="previewUrl" alt="待识别图片" />
      <LoadingOverlay v-if="phase === 'recognizing'" />
    </div>

    <!-- preview/recognizing:一行三钮;recognizing 全部禁用置灰、不可中断(U2) -->
    <div v-if="phase !== 'error'" class="actions">
      <el-button size="large" :disabled="phase === 'recognizing'" @click="$emit('retake')">
        {{ imageSource === 'camera' ? '重拍' : '重选' }}
      </el-button>
      <el-button
        type="primary"
        size="large"
        :disabled="phase === 'recognizing'"
        @click="$emit('confirm')"
      >
        确认识别
      </el-button>
      <el-button
        text
        size="large"
        :disabled="phase === 'recognizing'"
        @click="$emit('cancel')"
      >
        取消
      </el-button>
    </div>

    <!-- error:原按钮组隐藏,图下错误卡片(U3);失败不清空图片 -->
    <ErrorPanel
      v-else-if="phase === 'error' && error"
      :error="error"
      @retry="$emit('retry')"
      @reselect="$emit('reselect')"
    />
  </div>
</template>

<style scoped>
.preview-wrap {
  position: relative;
  background: #000;
  border-radius: 8px;
  overflow: hidden;
}

.preview-wrap img {
  display: block;
  width: 100%;
  max-height: 60vh;
  object-fit: contain;
}

.actions {
  margin-top: 20px;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 8px;
}
</style>
