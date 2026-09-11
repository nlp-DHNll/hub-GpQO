<script setup lang="ts">
import type { ResearchEvent } from '@/api/types'

const props = defineProps<{ events: ResearchEvent[] }>()

function describe(ev: ResearchEvent): { text: string; type: 'primary' | 'success' | 'warning' | 'danger' | 'info' } {
  switch (ev.type) {
    case 'created':
      return { text: `研究任务已创建:${ev.topic ?? ''}`, type: 'info' }
    case 'resumed':
      return { text: '服务重启,已从断点恢复继续研究', type: 'warning' }
    case 'plan':
      return { text: `已完成主题拆解,生成 ${ev.sub_questions?.length ?? 0} 个子问题`, type: 'primary' }
    case 'round_start':
      return { text: `—— 第 ${ev.round} 轮迭代开始 ——`, type: 'primary' }
    case 'search':
      return { text: `正在检索:${ev.queries?.join(' / ') ?? ''}`, type: 'primary' }
    case 'read':
      return {
        text: `已阅读 ${ev.urls?.length ?? 0} 页(正文 ${ev.ok ?? 0} 页,摘要兜底 ${ev.fallback ?? 0} 页)`,
        type: 'info',
      }
    case 'reflect':
      return {
        text: ev.sufficient ? '反思:信息已充分,准备生成报告' : `反思:还缺 ${ev.gaps ?? '部分信息'}`,
        type: ev.sufficient ? 'success' : 'warning',
      }
    case 'synthesize_start':
      return { text: '正在综合生成报告…', type: 'primary' }
    case 'report_done':
      return { text: '报告生成完成 ✓', type: 'success' }
    case 'aborted':
      return { text: '任务已取消(不生成报告)', type: 'danger' }
    case 'error':
      return { text: `任务失败:${ev.message ?? '未知错误'}`, type: 'danger' }
    default:
      return { text: ev.type, type: 'info' }
  }
}
</script>

<template>
  <el-timeline v-if="props.events.length">
    <el-timeline-item
      v-for="ev in props.events"
      :key="ev.id"
      :type="describe(ev).type"
      :timestamp="`事件 #${ev.id}`"
    >
      {{ describe(ev).text }}
      <div v-if="ev.type === 'plan' && ev.sub_questions?.length" class="sub-questions">
        <div v-for="(q, i) in ev.sub_questions" :key="i">{{ i + 1 }}. {{ q }}</div>
      </div>
    </el-timeline-item>
  </el-timeline>
  <el-empty v-else description="等待进度事件…" :image-size="60" />
</template>

<style scoped>
.sub-questions {
  margin-top: 6px;
  padding: 8px 12px;
  background: #f7f9fb;
  border-radius: 4px;
  color: #606266;
  font-size: 13px;
  line-height: 1.8;
}
</style>
