<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { fetchReports } from '@/api'
import type { ReportSummary } from '@/api/types'

const router = useRouter()
const loading = ref(true)
const items = ref<ReportSummary[]>([])

onMounted(async () => {
  try {
    items.value = await fetchReports()
  } finally {
    loading.value = false
  }
})

function open(row: ReportSummary) {
  router.push(`/report/${row.task_id}`)
}

function statusTag(status: string) {
  if (status === 'completed') return { label: '已完成', type: 'success' as const }
  if (status === 'incomplete') return { label: '不完整', type: 'warning' as const }
  return { label: status, type: 'info' as const }
}
</script>

<template>
  <el-card shadow="never" v-loading="loading">
    <template #header>
      <div class="header">
        <span>历史报告({{ items.length }})</span>
        <el-button type="primary" size="small" @click="router.push('/')">发起研究</el-button>
      </div>
    </template>
    <el-table :data="items" @row-click="open" class="clickable">
      <el-table-column prop="topic" label="研究主题" min-width="280" show-overflow-tooltip />
      <el-table-column prop="created_at" label="生成时间" width="170" />
      <el-table-column label="轮数" width="70">
        <template #default="{ row }">{{ row.stats.rounds }}</template>
      </el-table-column>
      <el-table-column label="搜索" width="70">
        <template #default="{ row }">{{ row.stats.searches }}</template>
      </el-table-column>
      <el-table-column label="阅读" width="70">
        <template #default="{ row }">{{ row.stats.pages_read }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.status).type" size="small">
            {{ statusTag(row.status).label }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && !items.length" description="暂无历史报告,去发起第一个研究吧" />
  </el-card>
</template>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.clickable :deep(tbody tr) {
  cursor: pointer;
}
</style>
