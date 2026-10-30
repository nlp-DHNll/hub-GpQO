<script setup lang="ts">
// 结果页(功能设计 §5,U4):缩略图 + 等级色块大标签 + 判定标准/R5 引导 + 主按钮
import { computed } from 'vue'
import { NOT_CORRIDOR_TIP, RESULT_META, type Level } from '../types'

const props = defineProps<{
  previewUrl: string | null
  level: Level
}>()

defineEmits<{ again: [] }>()

const meta = computed(() => RESULT_META[props.level])
</script>

<template>
  <div class="result-card">
    <!-- 上半:被识别图片缩略图(「识别的是这张」对照) -->
    <img v-if="previewUrl" class="thumb" :src="previewUrl" alt="被识别图片" />

    <!-- 下半:结果块 -->
    <div class="result-block">
      <div class="level-badge" :style="{ backgroundColor: meta.color }">
        {{ meta.label }}
      </div>
      <!-- not_corridor 不展示判定标准,改展示 R5 引导(S9) -->
      <p v-if="meta.criterion" class="criterion">{{ meta.criterion }}</p>
      <p v-else class="criterion guide">{{ NOT_CORRIDOR_TIP }}</p>
      <el-button type="primary" size="large" @click="$emit('again')">
        {{ level === 'not_corridor' ? '重新拍摄' : '再拍一张' }}
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.thumb {
  display: block;
  width: 100%;
  max-height: 44vh;
  object-fit: contain;
  border-radius: 8px;
  background: #000;
}

.result-block {
  margin-top: 24px;
  text-align: center;
}

.level-badge {
  display: inline-block;
  padding: 10px 32px;
  border-radius: 8px;
  color: #fff;
  font-size: 24px;
  font-weight: 600;
}

.criterion {
  margin: 16px 0 28px;
  font-size: 14px;
  color: #606266;
  line-height: 1.6;
}

.guide {
  color: #909399;
}
</style>
