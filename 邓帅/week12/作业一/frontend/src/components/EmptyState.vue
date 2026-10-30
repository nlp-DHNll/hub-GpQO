<script setup lang="ts">
// 空态:两个图片来源入口 ＋ 摄像头降级说明(功能设计 §2.1/§2.2)
defineProps<{ cameraAvailable: boolean }>()
defineEmits<{ camera: []; album: [] }>()
</script>

<template>
  <div class="empty-state">
    <h1 class="title">楼道消防隐患识别</h1>
    <p class="subtitle">拍摄楼道照片，即时判断消防隐患等级</p>
    <div class="entries">
      <el-button
        v-if="cameraAvailable"
        type="primary"
        size="large"
        @click="$emit('camera')"
      >
        拍照
      </el-button>
      <el-button
        :type="cameraAvailable ? 'default' : 'primary'"
        size="large"
        @click="$emit('album')"
      >
        相册上传
      </el-button>
    </div>
    <!-- D2 降级说明:仅摄像头不可用时出现 -->
    <p v-if="!cameraAvailable" class="camera-tip">
      当前环境不支持摄像头，可通过相册选择照片
    </p>
  </div>
</template>

<style scoped>
.empty-state {
  padding-top: 18vh;
  text-align: center;
}

.title {
  margin: 0 0 8px;
  font-size: 24px;
  color: #303133;
}

.subtitle {
  margin: 0 0 40px;
  font-size: 14px;
  color: #909399;
}

.entries {
  display: flex;
  justify-content: center;
  gap: 16px;
}

.entries .el-button {
  min-width: 128px;
}

.camera-tip {
  margin-top: 24px;
  font-size: 13px;
  color: #909399;
}
</style>
