<template>
  <div class="exception-page">
    <a-result status="404" title="404" sub-title="抱歉，您访问的页面不存在。">
      <template #extra>
        <a-space>
          <a-button type="primary" @click="goHome">
            <icon-home /> 返回首页
          </a-button>
          <a-button @click="goBack">
            <icon-arrow-left /> 返回上一页
          </a-button>
        </a-space>
      </template>
    </a-result>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { IconHome, IconArrowLeft } from '@arco-design/web-vue/es/icon'
const router = useRouter()
function goHome() { router.push('/dashboard') }
function goBack() {
  router.length > 1 ? router.back() : router.push('/dashboard')
}
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