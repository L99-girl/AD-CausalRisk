<template>
  <div class="exception-page">
    <a-result status="403" title="403" sub-title="抱歉，您没有访问此页面的权限。">
      <template #extra>
        <a-space>
          <a-button type="primary" @click="goLogin">
            <icon-poweroff /> 退出并重新登录
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
import { IconPoweroff, IconArrowLeft } from '@arco-design/web-vue/es/icon'
const router = useRouter()
function goLogin() {
  localStorage.removeItem('token')
  router.push('/login')
}
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