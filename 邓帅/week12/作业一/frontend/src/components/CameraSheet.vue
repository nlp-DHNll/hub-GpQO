<script setup lang="ts">
// 全屏取景层(功能设计 §2.3):取流→截帧/关闭即停流;失败在层内消化 D3 ＋相册出口
import { onBeforeUnmount, onMounted, ref } from 'vue'
import {
  CameraError,
  captureFrame,
  openStream,
  stopStream,
  type StreamErrorKind,
} from '../composables/useCamera'

const emit = defineEmits<{
  captured: [blob: Blob]
  close: []
  fallbackAlbum: []
}>()

const videoRef = ref<HTMLVideoElement | null>(null)
const streamError = ref<StreamErrorKind | null>(null)

onMounted(async () => {
  if (!videoRef.value) return
  try {
    await openStream(videoRef.value)
  } catch (err) {
    streamError.value = err instanceof CameraError ? err.kind : 'unknown'
  }
})

// 兜底:任何路径离开取景层都保证停流(U8)
onBeforeUnmount(stopStream)

async function onCapture() {
  if (!videoRef.value || streamError.value) return
  if (videoRef.value.videoWidth === 0) return // 帧未就绪时忽略误触
  const blob = await captureFrame(videoRef.value)
  stopStream()
  emit('captured', blob)
}

function onClose() {
  stopStream()
  emit('close')
}

function onFallbackAlbum() {
  stopStream()
  emit('fallbackAlbum')
}
</script>

<template>
  <div class="camera-sheet">
    <video v-show="!streamError" ref="videoRef" playsinline muted />
    <!-- D3 取景层调起失败提示 ＋ 改用相册出口 -->
    <div v-if="streamError" class="stream-error">
      <p>无法访问摄像头，请检查权限或改用相册上传</p>
      <div class="error-actions">
        <el-button type="primary" size="large" @click="onFallbackAlbum">改用相册上传</el-button>
        <el-button size="large" @click="onClose">关闭</el-button>
      </div>
    </div>
    <div v-else class="sheet-actions">
      <el-button size="large" @click="onClose">关闭</el-button>
      <el-button type="primary" size="large" round @click="onCapture">截帧</el-button>
    </div>
  </div>
</template>

<style scoped>
.camera-sheet {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: #000;
}

video {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.sheet-actions {
  position: absolute;
  bottom: calc(24px + env(safe-area-inset-bottom));
  left: 0;
  right: 0;
  display: flex;
  justify-content: center;
  gap: 48px;
}

.stream-error {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 24px;
  color: #e8e8e8;
  background: #1a1a1a;
  padding: 32px;
  text-align: center;
}

.error-actions {
  display: flex;
  gap: 16px;
}
</style>
