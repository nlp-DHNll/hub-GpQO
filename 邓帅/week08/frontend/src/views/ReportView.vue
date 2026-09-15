<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import MarkdownIt from 'markdown-it'
import { fetchReport } from '@/api'
import type { ReportDetail } from '@/api/types'
import ProcessPanel from '@/components/ProcessPanel.vue'
import SourceList from '@/components/SourceList.vue'

const route = useRoute()
const taskId = route.params.task_id as string

const loading = ref(true)
const error = ref('')
const detail = ref<ReportDetail | null>(null)

const md = new MarkdownIt({ html: false, linkify: true })
const rendered = computed(() =>
  detail.value ? md.render(detail.value.report_md) : '',
)

const statusTag = computed(() => {
  const s = detail.value?.process.status
  if (s === 'completed') return { label: '已完成', type: 'success' as const }
  if (s === 'incomplete') return { label: '不完整', type: 'warning' as const }
  if (s === 'aborted') return { label: '已取消', type: 'danger' as const }
  if (s === 'failed') return { label: '失败', type: 'danger' as const }
  return { label: s ?? '未知', type: 'info' as const }
})

onMounted(async () => {
  try {
    detail.value = await fetchReport(taskId)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-loading="loading">
    <el-alert v-if="error" type="error" :title="`报告加载失败:${error}`" show-icon :closable="false" />
    <template v-else-if="detail">
      <el-card shadow="never" class="report-card">
        <template #header>
          <div class="card-header">
            <span>研究报告</span>
            <el-tag :type="statusTag.type">{{ statusTag.label }}</el-tag>
          </div>
        </template>
        <!-- eslint-disable-next-line vue/no-v-html -->
        <div class="report-md" v-html="rendered" />
      </el-card>

      <el-card shadow="never" class="report-card">
        <template #header>来源列表({{ Object.keys(detail.process.sources).length }})</template>
        <SourceList :sources="detail.process.sources" />
      </el-card>

      <el-card shadow="never" class="report-card">
        <ProcessPanel :process="detail.process" />
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.report-card {
  margin-bottom: 16px;
}
</style>
