<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'

const router = useRouter()
const active = ref(router.currentRoute.value.path)

function navigate(path: string) {
  active.value = path
  router.push(path)
}
</script>

<template>
  <el-container>
    <el-header class="header">
      <div class="brand" @click="navigate('/')">
        <el-icon :size="20"><Search /></el-icon>
        <span>深度研究助手</span>
      </div>
      <el-menu mode="horizontal" :default-active="active" :ellipsis="false" @select="navigate" router>
        <el-menu-item index="/">发起研究</el-menu-item>
        <el-menu-item index="/history">历史报告</el-menu-item>
      </el-menu>
    </el-header>
    <el-main class="page">
      <router-view />
    </el-main>
  </el-container>
</template>

<style scoped>
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
}
.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 17px;
  font-weight: 600;
  cursor: pointer;
  color: #303133;
}
</style>
