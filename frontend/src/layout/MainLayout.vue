<template>
  <a-layout class="main-layout">
    <a-layout-sider
      v-model:collapsed="collapsed"
      collapsible
      :trigger="null"
      :width="220"
      :collapsed-width="64"
      class="sider"
    >
      <div class="logo-wrap">
        <div class="logo-icon">
          <icon-heart class="logo-heart" />
        </div>
        <transition name="fade">
          <div v-if="!collapsed" class="logo-text">
            <div class="logo-title">AD-CausalRisk</div>
            <div class="logo-sub">因果风险评估平台</div>
          </div>
        </transition>
      </div>

      <a-menu
        :selected-keys="selectedKeys"
        :open-keys="openKeys"
        mode="vertical"
        :theme="isDark ? 'dark' : 'light'"
        :auto-open-selected="true"
        @menu-item-click="onMenuClick"
        @sub-menu-click="onSubMenuClick"
        class="side-menu"
      >
        <a-menu-item key="dashboard">
          <icon-home />
          <template #title>首页</template>
        </a-menu-item>

        <a-sub-menu key="subject">
          <template #title>
            <icon-user-group />
            档案管理
          </template>
          <a-menu-item key="subject-list">
            受试者档案
          </a-menu-item>
          <a-menu-item key="subject-import" disabled>
            CSV 导入
          </a-menu-item>
        </a-sub-menu>

        <a-menu-item key="followup" disabled>
          <icon-clock-circle />
          <template #title>随访管理</template>
        </a-menu-item>

        <a-menu-item key="settings" disabled>
          <icon-settings />
          <template #title>系统设置</template>
        </a-menu-item>
      </a-menu>
    </a-layout-sider>

    <a-layout>
      <a-layout-header class="header">
        <div class="header-left">
          <a-button
            type="text"
            shape="circle"
            size="small"
            @click="collapsed = !collapsed"
          >
            <icon-menu-fold v-if="!collapsed" />
            <icon-menu-unfold v-else />
          </a-button>

          <a-breadcrumb class="breadcrumb">
            <a-breadcrumb-item v-for="(item, i) in breadcrumbs" :key="i">
              {{ item }}
            </a-breadcrumb-item>
          </a-breadcrumb>
        </div>

        <div class="header-right">
          <a-tooltip :content="isFullscreen ? '退出全屏' : '全屏'">
            <a-button type="text" shape="circle" size="small" @click="toggleFullscreen">
              <icon-fullscreen v-if="!isFullscreen" />
              <icon-fullscreen-exit v-else />
            </a-button>
          </a-tooltip>

          <a-tooltip content="刷新页面">
            <a-button type="text" shape="circle" size="small" @click="refreshPage">
              <icon-refresh />
            </a-button>
          </a-tooltip>

          <a-tooltip :content="isDark ? '亮色模式' : '暗黑模式'">
            <a-button type="text" shape="circle" size="small" @click="toggleTheme">
              <icon-sun v-if="isDark" />
              <icon-moon v-else />
            </a-button>
          </a-tooltip>

          <a-dropdown>
            <div class="user-info">
              <a-avatar :size="32" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%)">
                <template #icon><icon-user /></template>
              </a-avatar>
              <span class="user-name">{{ user?.username || 'Guest' }}</span>
              <icon-caret-down class="caret" />
            </div>
            <template #content>
              <a-doption disabled>个人中心（待实现）</a-doption>
              <a-doption disabled>账户设置（待实现）</a-doption>
              <a-doption @click="doLogout">
                <icon-poweroff style="margin-right: 6px" />
                退出登录
              </a-doption>
            </template>
          </a-dropdown>
        </div>
      </a-layout-header>

      <a-layout-content class="content">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </a-layout-content>
    </a-layout>
  </a-layout>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { logout } from '../api/auth.js'
import { useUserStore } from '../stores/user.js'

const DARK_ATTR = 'arco-theme'
const STORAGE_KEY = 'ad-causalrisk-theme'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const collapsed = ref(false)
const isFullscreen = ref(false)
const isDark = ref(false)

const user = computed(() => ({
  username: userStore.username,
  roles: userStore.roles
}))

const menuMap = {
  '/dashboard':  ['首页'],
  '/subjects':   ['首页', '档案管理', '档案列表'],
  '/followup':   ['首页', '随访管理'],
  '/settings':   ['首页', '系统设置']
}

const breadcrumbs = computed(() => {
  return menuMap[route.path] || ['首页']
})

const selectedKeys = computed(() => {
  if (route.path.startsWith('/subjects')) return ['subject-list']
  return [route.path.slice(1) || 'dashboard']
})

const openKeys = computed(() => {
  if (route.path.startsWith('/subjects')) return ['subject']
  return []
})

function onMenuClick(key) {
  const map = {
    'dashboard': '/dashboard',
    'subject-list': '/subjects'
  }
  if (map[key] && map[key] !== route.path) {
    router.push(map[key])
  }
}

function onSubMenuClick() {}

function toggleFullscreen() {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen?.()
    isFullscreen.value = true
  } else {
    document.exitFullscreen?.()
    isFullscreen.value = false
  }
}

function refreshPage() {
  window.location.reload()
}

function applyTheme(dark) {
  if (dark) {
    document.body.setAttribute(DARK_ATTR, 'dark')
  } else {
    document.body.removeAttribute(DARK_ATTR)
  }
}

function toggleTheme() {
  isDark.value = !isDark.value
}

watch(isDark, (val) => {
  applyTheme(val)
  localStorage.setItem(STORAGE_KEY, val ? 'dark' : 'light')
})

function doLogout() {
  logout()
  router.push('/login')
}

onMounted(() => {
  const saved = localStorage.getItem(STORAGE_KEY)
  const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches
  isDark.value = saved ? saved === 'dark' : !!prefersDark
  applyTheme(isDark.value)
})

document.addEventListener('fullscreenchange', () => {
  isFullscreen.value = !!document.fullscreenElement
})
</script>

<style scoped>
.main-layout {
  min-height: 100vh;
}

.sider {
  background: var(--color-bg-2);
  border-right: 1px solid var(--color-border-2);
  overflow: auto;
  transition: width 0.2s ease;
}

.logo-wrap {
  display: flex;
  align-items: center;
  padding: 18px 20px;
  gap: 12px;
  border-bottom: 1px solid var(--color-border-2);
  margin-bottom: 8px;
  overflow: hidden;
  white-space: nowrap;
}

.logo-icon {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.logo-heart {
  color: #fff;
  font-size: 20px;
}

.logo-text {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.logo-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text-1);
  letter-spacing: 0.3px;
}

.logo-sub {
  font-size: 11px;
  color: var(--color-text-3);
  margin-top: 2px;
}

.side-menu {
  background: transparent;
  border-right: none;
}

.side-menu :deep(.arco-menu-inner) {
  padding: 4px 12px;
}

.side-menu :deep(.arco-menu-item),
.side-menu :deep(.arco-sub-menu-title) {
  border-radius: 8px;
  margin-bottom: 2px;
  height: 40px;
  line-height: 40px;
}

.side-menu :deep(.arco-menu-item-selected) {
  background: linear-gradient(90deg, rgba(102, 126, 234, 0.15) 0%, rgba(118, 75, 162, 0.08) 100%);
  color: #165DFF;
  font-weight: 500;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 24px;
  background: var(--color-bg-2);
  border-bottom: 1px solid var(--color-border-2);
  height: 56px;
  line-height: 56px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.03);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.breadcrumb {
  line-height: 56px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.header-right .arco-btn {
  color: var(--color-text-2);
}

.header-right .arco-btn:hover {
  color: var(--color-primary-6);
  background: var(--color-fill-2);
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px 4px 4px;
  border-radius: 20px;
  cursor: pointer;
  transition: background 0.2s;
  margin-left: 8px;
}

.user-info:hover {
  background: var(--color-fill-2);
}

.user-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-1);
}

.caret {
  font-size: 10px;
  color: var(--color-text-3);
}

.content {
  background: var(--color-fill-2);
  min-height: calc(100vh - 56px);
  overflow: auto;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.18s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>