import { createRouter, createWebHashHistory } from 'vue-router'

// hash 路由:演示模式由 FastAPI StaticFiles 托管,刷新无需服务端回退
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      name: 'research',
      component: () => import('@/views/ResearchView.vue'),
    },
    {
      path: '/report/:task_id',
      name: 'report',
      component: () => import('@/views/ReportView.vue'),
    },
    {
      path: '/history',
      name: 'history',
      component: () => import('@/views/HistoryView.vue'),
    },
  ],
})

export default router
