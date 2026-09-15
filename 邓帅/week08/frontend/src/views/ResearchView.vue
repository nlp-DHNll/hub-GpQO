<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { cancelResearch, startResearch } from '@/api'
import { subscribeEvents, type SSEHandle } from '@/api/sse'
import type { ResearchEvent, TaskStatus } from '@/api/types'
import ProgressTimeline from '@/components/ProgressTimeline.vue'

const route = useRoute()
const router = useRouter()
const topic = ref('')
const submitting = ref(false)
const taskId = ref('')
const phase = ref<'form' | 'running' | 'aborted' | 'failed'>('form')
const events = ref<ResearchEvent[]>([])
const terminalStatus = ref<TaskStatus | ''>('')

let sse: SSEHandle | null = null

function followTask(id: string) {
  taskId.value = id
  phase.value = 'running'
  events.value = []
  sse = subscribeEvents(
    id,
    (ev) => events.value.push(ev),
    (ev) => {
      if (ev.type === 'report_done') {
        router.push(`/report/${id}`)
      } else if (ev.type === 'aborted') {
        phase.value = 'aborted'
        terminalStatus.value = 'aborted'
      } else if (ev.type === 'error') {
        phase.value = 'failed'
        terminalStatus.value = 'failed'
      }
    },
  )
}

// 支持 /?task=xxx 直达某任务进度(刷新/分享/演示用)
onMounted(() => {
  const t = route.query.task as string | undefined
  if (t) followTask(t)
})

async function submit() {
  if (topic.value.trim().length < 2) {
    ElMessage.warning('请输入研究主题(至少 2 个字符)')
    return
  }
  submitting.value = true
  try {
    const { task_id } = await startResearch(topic.value.trim())
    followTask(task_id)
  } catch (e) {
    ElMessage.error(`发起研究失败:${(e as Error).message}`)
  } finally {
    submitting.value = false
  }
}

async function cancel() {
  if (!taskId.value) return
  try {
    await cancelResearch(taskId.value)
    ElMessage.info('已发送取消请求')
  } catch (e) {
    ElMessage.error((e as Error).message)
  }
}

function reset() {
  sse?.close()
  sse = null
  phase.value = 'form'
  taskId.value = ''
  events.value = []
  terminalStatus.value = ''
}

onBeforeUnmount(() => sse?.close())
</script>

<template>
  <!-- 发起表单 -->
  <el-card v-if="phase === 'form'" shadow="never">
    <template #header>发起深度研究</template>
    <el-input
      v-model="topic"
      size="large"
      placeholder="输入研究主题,如:国产新能源车企智驾方案对比"
      @keyup.enter="submit"
    >
      <template #append>
        <el-button :loading="submitting" @click="submit">开始研究</el-button>
      </template>
    </el-input>
    <el-alert
      class="hint"
      type="info"
      :closable="false"
      title="系统将自动:拆解子问题 → 多轮检索与阅读 → 反思信息缺口 → 综合生成带来源引用的研究报告"
    />
  </el-card>

  <!-- 进度视图 -->
  <el-card v-else shadow="never">
    <template #header>
      <div class="progress-header">
        <span>研究进度{{ taskId ? `(${taskId})` : '' }}</span>
        <div class="actions">
          <el-button v-if="phase === 'running'" type="danger" plain size="small" @click="cancel">
            取消任务
          </el-button>
          <el-button v-if="phase !== 'running'" size="small" @click="reset">发起新研究</el-button>
        </div>
      </div>
    </template>

    <el-result
      v-if="phase === 'aborted'"
      icon="warning"
      title="任务已取消"
      sub-title="任务被取消,不生成报告;可返回发起新研究"
    />
    <el-result
      v-else-if="phase === 'failed'"
      icon="error"
      title="任务失败"
      :sub-title="events.at(-1)?.message ?? '研究过程发生异常'"
    />
    <template v-else>
      <div class="running-banner">
        <el-icon class="is-loading"><Loading /></el-icon>
        研究进行中… 事件数:{{ events.length }}
      </div>
      <ProgressTimeline :events="events" />
    </template>
  </el-card>
</template>

<style scoped>
.hint {
  margin-top: 16px;
}
.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.running-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #409eff;
  margin-bottom: 16px;
  font-size: 14px;
}
</style>
