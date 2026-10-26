<template>
  <div class="exception-page">
    <a-result status="500" title="500" sub-title="服务器开小差了，请稍后再试。">
      <template #extra>
        <a-space>
          <a-button type="primary" @click="refresh">
            <icon-refresh /> 重新加载
          </a-button>
          <a-button @click="goHome">
            <icon-home /> 返回首页
          </a-button>
        </a-space>
      </template>
    </a-result>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { IconRefresh, IconHome } from '@arco-design/web-vue/es/icon'
const router = useRouter()
function refresh() { window.location.reload() }
function goHome() { router.push('/dashboard') }
</script>

<style scoped>
.exception-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 56px - 40px);
  padding: 40px;
}
</style>