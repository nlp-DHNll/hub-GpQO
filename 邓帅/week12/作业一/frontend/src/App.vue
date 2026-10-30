<script setup lang="ts">
// 状态机唯一持有者(技术设计 §3.1,T9):七字段 + 九动作,props/emits 向下通信
import { onMounted, ref, watch } from 'vue'
import { ApiRequestError, recognize } from './api'
import { compressImage } from './composables/useCompress'
import { detectCameraAvailable } from './composables/useCamera'
import type { ApiError, ImageSource, Level, Phase } from './types'
import CameraSheet from './components/CameraSheet.vue'
import EmptyState from './components/EmptyState.vue'
import PreviewConfirm from './components/PreviewConfirm.vue'
import ResultCard from './components/ResultCard.vue'

// —— 状态机字段(技术设计 §3.1) ——
const phase = ref<Phase>('empty')
const imageSource = ref<ImageSource | null>(null)
const imageFile = ref<File | null>(null) // 压缩后唯一图片对象,失败态不清空
const level = ref<Level | null>(null)
const error = ref<ApiError | null>(null)
const cameraAvailable = ref(false)
const cameraSheetOpen = ref(false)

// 隐藏 file input 单例(T10):空态入口、U6 回跳、失败态「重新选择」共用
const fileInput = ref<HTMLInputElement | null>(null)

// 压缩后仍超 10MB 的极端情形前端拦截(U11)
const MAX_UPLOAD_SIZE = 10 * 1024 * 1024

// imageFile 的 object URL(预览/结果页共用),切换图片时回收旧 URL
const previewUrl = ref<string | null>(null)
watch(imageFile, (file) => {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = file ? URL.createObjectURL(file) : null
})

// 摄像头一次性特性探测缓存(功能设计 §2.2)
onMounted(() => {
  cameraAvailable.value = detectCameraAvailable()
})

// —— 动作函数(技术设计 §3.1 动作表) ——

function openCamera() {
  cameraSheetOpen.value = true
}

function openAlbum() {
  fileInput.value?.click()
}

/** 图片就绪(截帧/选图)→ 压缩 → 预览;压缩后仍超限直接失败态(U11)。 */
async function onImageReady(raw: Blob, source: ImageSource) {
  const name = source === 'camera' ? 'capture.jpg' : 'upload.jpg'
  const file = await compressImage(raw, name)
  imageFile.value = file
  imageSource.value = source
  level.value = null
  error.value = null
  if (file.size > MAX_UPLOAD_SIZE) {
    failInvalidFile()
    return
  }
  phase.value = 'preview'
}

/** 进失败态并展示 E1 文案(压缩后超限/压缩失败共用)。 */
function failInvalidFile() {
  error.value = { code: 'INVALID_FILE' }
  phase.value = 'error'
}

/** 确认识别 → 上传 → 结果/失败。 */
async function confirmRecognize() {
  if (!imageFile.value || phase.value === 'recognizing') return
  phase.value = 'recognizing'
  error.value = null
  try {
    level.value = await recognize(imageFile.value)
    phase.value = 'result'
  } catch (err) {
    error.value =
      err instanceof ApiRequestError ? err.apiError : { code: 'NETWORK' }
    phase.value = 'error'
  }
}

/** 取消:清空图片回空态(功能设计 §1.2)。 */
function cancelPreview() {
  clearImage()
  phase.value = 'empty'
}

/** 重拍/重选:回来源取新图,替换后经 onImageReady 停留预览态。 */
function retakeOrReselect() {
  if (imageSource.value === 'camera') cameraSheetOpen.value = true
  else fileInput.value?.click()
}

/** 重试:同一张 imageFile 重新上传,次数不限。 */
function retryRecognize() {
  confirmRecognize()
}

/** 再拍一张/重新选择/重新拍摄:回空态后直接调起原来源(U6)。 */
function reopenSource() {
  const source = imageSource.value
  clearImage()
  phase.value = 'empty'
  if (source === 'camera' && cameraAvailable.value) cameraSheetOpen.value = true
  else fileInput.value?.click()
}

function clearImage() {
  imageFile.value = null
  imageSource.value = null
  level.value = null
  error.value = null
}

// —— 事件桥 ——

async function onCaptured(blob: Blob) {
  cameraSheetOpen.value = false
  try {
    await onImageReady(blob, 'camera')
  } catch {
    failInvalidFile() // 压缩失败兜底(与相册路径一致)
  }
}

function onFallbackAlbum() {
  cameraSheetOpen.value = false
  fileInput.value?.click()
}

async function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = '' // U9:清空 value,重复选同一张也能再次触发 change
  if (!file) return
  try {
    await onImageReady(file, 'album')
  } catch {
    // 压缩失败(非图片/损坏图;accept 正常路径选不到,此处为构造文件兜底)
    failInvalidFile()
  }
}
</script>

<template>
  <div class="page">
    <!-- 隐藏 file input 单例(T10) -->
    <input ref="fileInput" type="file" accept="image/*" hidden @change="onFileChange" />

    <EmptyState
      v-if="phase === 'empty'"
      :camera-available="cameraAvailable"
      @camera="openCamera"
      @album="openAlbum"
    />

    <PreviewConfirm
      v-else-if="phase === 'preview' || phase === 'recognizing' || phase === 'error'"
      :preview-url="previewUrl"
      :phase="phase"
      :image-source="imageSource"
      :error="error"
      @confirm="confirmRecognize"
      @retake="retakeOrReselect"
      @cancel="cancelPreview"
      @retry="retryRecognize"
      @reselect="reopenSource"
    />

    <ResultCard
      v-else-if="phase === 'result' && level"
      :preview-url="previewUrl"
      :level="level"
      @again="reopenSource"
    />

    <!-- 全屏取景层,独立于五态之上 -->
    <CameraSheet
      v-if="cameraSheetOpen"
      @captured="onCaptured"
      @close="cameraSheetOpen = false"
      @fallback-album="onFallbackAlbum"
    />
  </div>
</template>
