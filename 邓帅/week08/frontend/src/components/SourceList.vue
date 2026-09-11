<script setup lang="ts">
import type { SourceMeta } from '@/api/types'

const props = defineProps<{ sources: Record<string, SourceMeta> }>()

const entries = Object.entries(props.sources ?? {})
</script>

<template>
  <div class="sources">
    <div v-for="[url, meta], i in entries" :key="url" class="source-item">
      <div class="source-title">
        <span class="index">[{{ i + 1 }}]</span>
        <span>{{ meta.title || '(无标题)' }}</span>
        <el-tag v-if="meta.from_summary" size="small" type="warning">基于摘要</el-tag>
        <el-tag v-if="meta.cited" size="small" type="info">被引 {{ meta.cited }} 次</el-tag>
      </div>
      <div class="source-url">
        <a :href="url" target="_blank" rel="noopener">{{ url }}</a>
      </div>
      <div v-if="meta.summary" class="source-summary">{{ meta.summary }}</div>
    </div>
    <el-empty v-if="!entries.length" description="无来源" :image-size="60" />
  </div>
</template>

<style scoped>
.source-item {
  padding: 10px 12px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  margin-bottom: 10px;
  background: #fff;
}
.source-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 14px;
}
.index {
  color: #409eff;
  font-family: monospace;
}
.source-url {
  margin-top: 4px;
  font-size: 13px;
  word-break: break-all;
}
.source-summary {
  margin-top: 4px;
  font-size: 13px;
  color: #909399;
  line-height: 1.6;
}
</style>
