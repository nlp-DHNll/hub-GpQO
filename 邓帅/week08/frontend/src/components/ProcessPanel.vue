<script setup lang="ts">
import type { ResearchProcess } from '@/api/types'

const props = defineProps<{ process: ResearchProcess }>()
</script>

<template>
  <el-collapse>
    <el-collapse-item title="研究过程记录" name="process">
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="迭代轮数">{{ props.process.stats.rounds }}</el-descriptions-item>
        <el-descriptions-item label="搜索次数">{{ props.process.stats.searches }}</el-descriptions-item>
        <el-descriptions-item label="阅读页数">{{ props.process.stats.pages_read }}</el-descriptions-item>
        <el-descriptions-item label="模型">{{ props.process.model }}</el-descriptions-item>
      </el-descriptions>

      <div class="block-title">子问题拆解</div>
      <ol class="plain-list">
        <li v-for="(q, i) in props.process.plan" :key="i">{{ q }}</li>
      </ol>

      <div class="block-title">轮次明细</div>
      <div v-for="r in props.process.rounds" :key="r.round" class="round-item">
        <div class="round-head">第 {{ r.round }} 轮</div>
        <div>检索查询:{{ r.queries.join(' / ') || '(无)' }}</div>
        <div v-if="r.failed_queries?.length" class="warn">失败查询:{{ r.failed_queries.join(' / ') }}</div>
        <div>阅读页面:{{ r.read_urls?.length ?? 0 }} 页,新增要点 {{ r.findings_added ?? 0 }} 条</div>
        <div v-if="r.gaps">反思:{{ r.gaps }}</div>
      </div>
    </el-collapse-item>
  </el-collapse>
</template>

<style scoped>
.block-title {
  font-weight: 600;
  margin: 14px 0 8px;
  font-size: 14px;
}
.plain-list {
  margin: 0;
  padding-left: 20px;
  color: #606266;
  font-size: 13px;
  line-height: 1.8;
}
.round-item {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 8px 12px;
  margin-bottom: 8px;
  font-size: 13px;
  color: #606266;
  line-height: 1.8;
}
.round-head {
  font-weight: 600;
  color: #303133;
}
.warn {
  color: #e6a23c;
}
</style>
