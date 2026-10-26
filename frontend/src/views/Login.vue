<template>
  <div class="login-page">
    <div class="bg-decor">
      <svg class="bg-grid" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <defs>
          <pattern id="dot-pattern" x="0" y="0" width="28" height="28" patternUnits="userSpaceOnUse">
            <circle cx="2" cy="2" r="1.3" fill="rgba(22, 93, 255, 0.12)" />
          </pattern>
          <pattern id="grid-pattern" x="0" y="0" width="80" height="80" patternUnits="userSpaceOnUse">
            <path d="M 80 0 L 0 0 0 80" fill="none" stroke="rgba(22, 93, 255, 0.06)" stroke-width="1" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#grid-pattern)" />
        <rect width="100%" height="100%" fill="url(#dot-pattern)" />
      </svg>
      <div class="blob blob-1"></div>
      <div class="blob blob-2"></div>
      <div class="blob blob-3"></div>
      <div class="deco-ring ring-a"></div>
      <div class="deco-ring ring-b"></div>
      <div class="deco-dot dot-1"></div>
      <div class="deco-dot dot-2"></div>
      <div class="deco-dot dot-3"></div>
      <svg class="deco-wave" viewBox="0 0 1440 120" preserveAspectRatio="none">
        <path d="M0,60 C240,120 480,0 720,60 C960,120 1200,0 1440,60 L1440,120 L0,120 Z" fill="rgba(22, 93, 255, 0.04)"/>
      </svg>
    </div>

    <main class="page-main">
      <div class="login-shell">
        <div class="login-card" :class="{ 'swap-panels': isSignUp }">
          <div class="form-side">
            <div class="form-slide sign-in-slide">
              <div class="form-header">
                <svg class="mini-logo" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg">
                  <rect x="2" y="2" width="28" height="28" rx="8" fill="url(#miniGrad)"/>
                  <path d="M9 20 L14 10 L19 20 M10.5 17 L17.5 17" stroke="#fff" stroke-width="2.2" stroke-linecap="round" fill="none"/>
                  <defs><linearGradient id="miniGrad" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" style="stop-color:#165DFF"/><stop offset="100%" style="stop-color:#4080FF"/></linearGradient></defs>
                </svg>
                <span class="mini-brand">AD-CausalRisk</span>
              </div>

              <h2 class="form-title">Sign in to<br/><span class="brand-hl">Your Account</span></h2>

              <div class="social-row">
                <div class="social-btn" title="GitHub">
                  <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 .5C5.73.5.74 5.5.74 11.77c0 4.99 3.23 9.22 7.71 10.71.56.1.77-.25.77-.55 0-.27-.01-1-.02-1.96-3.14.68-3.8-1.52-3.8-1.52-.52-1.32-1.27-1.67-1.27-1.67-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.19 1.76 1.19 1.02 1.76 2.69 1.25 3.34.96.1-.74.4-1.25.72-1.54-2.5-.28-5.13-1.25-5.13-5.57 0-1.23.44-2.24 1.16-3.03-.12-.28-.5-1.43.11-2.98 0 0 .95-.3 3.11 1.15.9-.25 1.87-.38 2.83-.38.96 0 1.93.13 2.83.38 2.16-1.45 3.1-1.15 3.1-1.15.61 1.55.23 2.7.11 2.98.72.79 1.16 1.8 1.16 3.03 0 4.33-2.63 5.29-5.14 5.56.41.35.77 1.05.77 2.12 0 1.53-.01 2.76-.01 3.13 0 .3.2.66.78.55 4.47-1.49 7.7-5.72 7.7-10.71C23.26 5.5 18.27.5 12 .5z"/></svg>
                </div>
                <div class="social-btn" title="Google">
                  <svg viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
                </div>
                <div class="social-btn" title="WeChat">
                  <svg viewBox="0 0 24 24" fill="#07C160"><path d="M8.691 2.188C3.891 2.188 0 5.476 0 9.53c0 2.212 1.17 4.203 3.002 5.55a.59.59 0 0 1 .213.665l-.39 1.48c-.019.07-.048.141-.048.213 0 .163.13.295.29.295a.326.326 0 0 0 .167-.054l1.903-1.114a.864.864 0 0 1 .717-.098 10.16 10.16 0 0 0 2.837.403c.276 0 .543-.027.811-.05-.857-2.578.157-4.972 1.932-6.446 1.703-1.415 3.882-1.98 5.853-1.838-.576-3.583-4.196-6.348-8.596-6.348zM5.785 5.991c.642 0 1.162.529 1.162 1.18a1.17 1.17 0 0 1-1.162 1.178A1.17 1.17 0 0 1 4.623 7.17c0-.651.52-1.18 1.162-1.18zm5.813 0c.642 0 1.162.529 1.162 1.18a1.17 1.17 0 0 1-1.162 1.178 1.17 1.17 0 0 1-1.162-1.178c0-.651.52-1.18 1.162-1.18zm5.34 2.867c-1.797-.052-3.746.512-5.28 1.786-1.72 1.428-2.687 3.72-1.78 6.22.942 2.453 3.666 4.229 6.884 4.229.826 0 1.622-.12 2.361-.336a.722.722 0 0 1 .598.082l1.584.926a.272.272 0 0 0 .14.047c.134 0 .24-.111.24-.247 0-.06-.023-.12-.038-.177l-.327-1.233a.582.582 0 0 1-.023-.156.49.49 0 0 1 .201-.398C23.024 18.48 24 16.82 24 14.98c0-3.21-2.931-5.837-6.656-6.088V8.89c-.135-.01-.27-.027-.407-.032zm-2.53 3.274c.535 0 .969.44.969.982a.976.976 0 0 1-.969.983.976.976 0 0 1-.969-.983c0-.542.434-.982.97-.982zm4.844 0c.535 0 .969.44.969.982a.976.976 0 0 1-.969.983.976.976 0 0 1-.969-.983c0-.542.434-.982.969-.982z"/></svg>
                </div>
              </div>

              <div class="divider"><span>or continue with email</span></div>

              <a-form ref="formRef" :model="form" :rules="rules" layout="vertical" size="large" class="auth-form">
                <a-form-item field="username" :required="true">
                  <a-input v-model="form.username" placeholder="请输入用户名" allow-clear class="auth-input">
                    <template #prefix><icon-user class="in-ico" /></template>
                  </a-input>
                </a-form-item>
                <a-form-item field="password" :required="true">
                  <a-input-password v-model="form.password" placeholder="请输入密码" class="auth-input">
                    <template #prefix><icon-lock class="in-ico" /></template>
                  </a-input-password>
                </a-form-item>
                <a-form-item field="captcha" :required="true">
                  <div class="captcha-row">
                    <a-input v-model="form.captcha" placeholder="请输入验证码" allow-clear class="captcha-input" @keyup.enter="handleFormSubmit">
                      <template #prefix><icon-safe class="in-ico" /></template>
                    </a-input>
                    <canvas ref="captchaCanvas" width="112" height="40" class="captcha-canvas" title="点击刷新验证码" @click="refreshCaptcha"></canvas>
                  </div>
                </a-form-item>

                <div v-if="error" class="err-alert">
                  <icon-close-circle-fill />
                  <span>{{ error }}</span>
                </div>

                <div class="form-options">
                  <a-checkbox v-model:checked="form.remember">记住账号</a-checkbox>
                  <a-link class="forgot-link" @click="showForgotModal = true">忘记密码？</a-link>
                </div>

                <button html-type="button" class="btn-primary" :disabled="loading" @click="handleFormSubmit">
                  <template v-if="!loading">Sign In</template>
                  <template v-else><span class="btn-spinner"></span>登录中...</template>
                </button>
              </a-form>

              <div class="form-footer-info">
                <span class="mode-hint">{{ isMock ? '演示 · admin/admin' : '真实后端 · admin/DemoPass!2026' }}</span>
                <a-tag v-if="isMock" color="orangered" size="small">Mock</a-tag>
                <a-tag v-else color="green" size="small">Live</a-tag>
              </div>
            </div>

            <div class="form-slide sign-up-slide">
              <div class="form-header">
                <svg class="mini-logo" viewBox="0 0 32 32"><rect x="2" y="2" width="28" height="28" rx="8" fill="url(#miniGrad2)"/><path d="M9 20 L14 10 L19 20 M10.5 17 L17.5 17" stroke="#fff" stroke-width="2.2" stroke-linecap="round" fill="none"/><defs><linearGradient id="miniGrad2" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" style="stop-color:#165DFF"/><stop offset="100%" style="stop-color:#4080FF"/></linearGradient></defs></svg>
                <span class="mini-brand">AD-CausalRisk</span>
              </div>

              <h2 class="form-title">Create<br/><span class="brand-hl">New Account</span></h2>

              <div class="social-row">
                <div class="social-btn" title="GitHub"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 .5C5.73.5.74 5.5.74 11.77c0 4.99 3.23 9.22 7.71 10.71.56.1.77-.25.77-.55 0-.27-.01-1-.02-1.96-3.14.68-3.8-1.52-3.8-1.52-.52-1.32-1.27-1.67-1.27-1.67-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.19 1.76 1.19 1.02 1.76 2.69 1.25 3.34.96.1-.74.4-1.25.72-1.54-2.5-.28-5.13-1.25-5.13-5.57 0-1.23.44-2.24 1.16-3.03-.12-.28-.5-1.43.11-2.98 0 0 .95-.3 3.11 1.15.9-.25 1.87-.38 2.83-.38.96 0 1.93.13 2.83.38 2.16-1.45 3.1-1.15 3.1-1.15.61 1.55.23 2.7.11 2.98.72.79 1.16 1.8 1.16 3.03 0 4.33-2.63 5.29-5.14 5.56.41.35.77 1.05.77 2.12 0 1.53-.01 2.76-.01 3.13 0 .3.2.66.78.55 4.47-1.49 7.7-5.72 7.7-10.71C23.26 5.5 18.27.5 12 .5z"/></svg></div>
                <div class="social-btn" title="Google"><svg viewBox="0 0 24 24"><path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg></div>
                <div class="social-btn" title="WeChat"><svg viewBox="0 0 24 24" fill="#07C160"><path d="M8.691 2.188C3.891 2.188 0 5.476 0 9.53c0 2.212 1.17 4.203 3.002 5.55a.59.59 0 0 1 .213.665l-.39 1.48c-.019.07-.048.141-.048.213 0 .163.13.295.29.295a.326.326 0 0 0 .167-.054l1.903-1.114a.864.864 0 0 1 .717-.098 10.16 10.16 0 0 0 2.837.403c.276 0 .543-.027.811-.05-.857-2.578.157-4.972 1.932-6.446 1.703-1.415 3.882-1.98 5.853-1.838-.576-3.583-4.196-6.348-8.596-6.348zM5.785 5.991c.642 0 1.162.529 1.162 1.18a1.17 1.17 0 0 1-1.162 1.178A1.17 1.17 0 0 1 4.623 7.17c0-.651.52-1.18 1.162-1.18zm5.813 0c.642 0 1.162.529 1.162 1.18a1.17 1.17 0 0 1-1.162 1.178 1.17 1.17 0 0 1-1.162-1.178c0-.651.52-1.18 1.162-1.18zm5.34 2.867c-1.797-.052-3.746.512-5.28 1.786-1.72 1.428-2.687 3.72-1.78 6.22.942 2.453 3.666 4.229 6.884 4.229.826 0 1.622-.12 2.361-.336a.722.722 0 0 1 .598.082l1.584.926a.272.272 0 0 0 .14.047c.134 0 .24-.111.24-.247 0-.06-.023-.12-.038-.177l-.327-1.233a.582.582 0 0 1-.023-.156.49.49 0 0 1 .201-.398C23.024 18.48 24 16.82 24 14.98c0-3.21-2.931-5.837-6.656-6.088V8.89c-.135-.01-.27-.027-.407-.032zm-2.53 3.274c.535 0 .969.44.969.982a.976.976 0 0 1-.969.983.976.976 0 0 1-.969-.983c0-.542.434-.982.97-.982zm4.844 0c.535 0 .969.44.969.982a.976.976 0 0 1-.969.983.976.976 0 0 1-.969-.983c0-.542.434-.982.969-.982z"/></svg></div>
                <div class="social-btn" title="WeChat"><svg viewBox="0 0 24 24" fill="#07C160"><path d="M8.691 2.188C3.891 2.188 0 5.476 0 9.53c0 2.212 1.17 4.203 3.002 5.55a.59.59 0 0 1 .213.665l-.39 1.48c-.019.07-.048.141-.048.213 0 .163.13.295.29.295a.326.326 0 0 0 .167-.054l1.903-1.114a.864.864 0 0 1 .717-.098 10.16 10.16 0 0 0 2.837.403c.276 0 .543-.027.811-.05-.857-2.578.157-4.972 1.932-6.446 1.703-1.415 3.882-1.98 5.853-1.838-.576-3.583-4.196-6.348-8.596-6.348z"/></svg></div>
              </div>

              <div class="divider"><span>or sign up with email</span></div>

              <a-form ref="signupFormRef" :model="signupForm" :rules="signupRules" layout="vertical" size="large" class="auth-form">
                <a-form-item field="username" :required="true">
                  <a-input v-model="signupForm.username" placeholder="用户名" class="auth-input">
                    <template #prefix><icon-user class="in-ico" /></template>
                  </a-input>
                </a-form-item>
                <a-form-item field="email" :required="true">
                  <a-input v-model="signupForm.email" placeholder="邮箱地址" class="auth-input">
                    <template #prefix><icon-safe class="in-ico" /></template>
                  </a-input>
                </a-form-item>
                <a-form-item field="password" :required="true">
                  <a-input-password v-model="signupForm.password" placeholder="密码" class="auth-input">
                    <template #prefix><icon-lock class="in-ico" /></template>
                  </a-input-password>
                </a-form-item>
                <a-form-item field="confirmPassword" :required="true">
                  <a-input-password v-model="signupForm.confirmPassword" placeholder="确认密码" class="auth-input">
                    <template #prefix><icon-lock class="in-ico" /></template>
                  </a-input-password>
                </a-form-item>
                <button html-type="button" class="btn-primary" @click="handleSignup">Sign Up</button>
              </a-form>
            </div>
          </div>

          <div class="brand-side">
            <div class="brand-slide welcome-slide">
              <h1 class="brand-h1">Welcome Back!</h1>
              <p class="brand-desc">已有账号？返回登录继续使用 AD-CausalRisk 平台。</p>
              <button class="btn-ghost" @click="isSignUp = false">Sign In</button>
            </div>
            <div class="brand-slide friend-slide">
              <h1 class="brand-h1">Hello, Friend!</h1>
              <p class="brand-desc">还没有账号？创建一个新账号，开启您的研究旅程。</p>
              <div class="brand-features">
                <div class="bf-item"><icon-check-circle /> 多中心数据接入</div>
                <div class="bf-item"><icon-check-circle /> 因果推断模型</div>
                <div class="bf-item"><icon-check-circle /> 全链路质量监控</div>
              </div>
              <button class="btn-ghost" @click="isSignUp = true">Sign Up</button>
            </div>
            <div class="brand-pattern">
              <svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
                <circle cx="100" cy="100" r="70" fill="none" stroke="rgba(255,255,255,0.12)" stroke-width="1" />
                <circle cx="100" cy="100" r="50" fill="none" stroke="rgba(255,255,255,0.1)" stroke-width="1" />
                <circle cx="100" cy="100" r="30" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="1" />
                <circle cx="100" cy="30" r="3" fill="rgba(255,255,255,0.3)" />
                <circle cx="160" cy="100" r="3" fill="rgba(255,255,255,0.3)" />
                <circle cx="100" cy="170" r="3" fill="rgba(255,255,255,0.3)" />
                <circle cx="40" cy="100" r="3" fill="rgba(255,255,255,0.3)" />
                <circle cx="140" cy="60" r="2" fill="rgba(255,255,255,0.2)" />
                <circle cx="140" cy="140" r="2" fill="rgba(255,255,255,0.2)" />
                <circle cx="60" cy="140" r="2" fill="rgba(255,255,255,0.2)" />
                <circle cx="60" cy="60" r="2" fill="rgba(255,255,255,0.2)" />
              </svg>
            </div>
          </div>
        </div>
      </div>
    </main>

    <footer class="page-footer">
      © 2026 AD-CausalRisk · 阿尔茨海默病因果风险评估平台 · v1.0.0
    </footer>

    <a-modal v-model:visible="showForgotModal" title="找回密码" :footer="false" :mask-closable="true" :unmount-on-close="true" :width="400">
      <div class="forgot-content">
        <icon-exclamation-circle-fill class="forgot-icon" />
        <p class="forgot-text">如忘记密码，请联系系统管理员重置。</p>
        <p class="forgot-contact">管理员邮箱：admin@adcausalrisk.org</p>
        <a-button type="primary" long @click="showForgotModal = false">我知道了</a-button>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import { IconUser, IconLock, IconSafe, IconCloseCircleFill, IconCheckCircle, IconExclamationCircleFill } from '@arco-design/web-vue/es/icon'
import { login } from '../api/auth.js'

const router = useRouter()
const formRef = ref(null)
const signupFormRef = ref(null)
const captchaCanvas = ref(null)
const isMock = import.meta.env.VITE_USE_MOCK !== 'false'

const isSignUp = ref(false)
const loading = ref(false)
const error = ref('')
const captchaCode = ref('')
const showForgotModal = ref(false)

const CAPTCHA_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'

function randChar() { return CAPTCHA_CHARS.charAt(Math.floor(Math.random() * CAPTCHA_CHARS.length)) }
function randColor(min, max) {
  const r = Math.floor(Math.random() * (max - min) + min)
  const g = Math.floor(Math.random() * (max - min) + min)
  const b = Math.floor(Math.random() * (max - min) + min)
  return `rgb(${r},${g},${b})`
}

function drawCaptcha() {
  const canvas = captchaCanvas.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  const w = canvas.width; const h = canvas.height
  ctx.fillStyle = '#eef2ff'; ctx.fillRect(0, 0, w, h)
  ctx.strokeStyle = '#c9d4f0'; ctx.lineWidth = 1
  for (let i = 0; i < 4; i++) {
    ctx.beginPath()
    ctx.moveTo(Math.random() * w, Math.random() * h)
    ctx.lineTo(Math.random() * w, Math.random() * h)
    ctx.stroke()
  }
  ctx.fillStyle = '#a3b4e8'
  for (let i = 0; i < 28; i++) {
    ctx.beginPath(); ctx.arc(Math.random() * w, Math.random() * h, 1, 0, Math.PI * 2); ctx.fill()
  }
  let code = ''
  for (let i = 0; i < 4; i++) {
    const ch = randChar(); code += ch
    ctx.font = `bold ${22 + Math.random() * 6}px "Georgia", serif`
    ctx.fillStyle = randColor(30, 100)
    ctx.save()
    const x = 16 + i * 24; const y = 26 + Math.random() * 6
    ctx.translate(x, y); ctx.rotate((Math.random() - 0.5) * 0.5); ctx.fillText(ch, 0, 0); ctx.restore()
  }
  captchaCode.value = code
}

function refreshCaptcha() { form.value.captcha = ''; drawCaptcha() }
onMounted(drawCaptcha)

const form = reactive({ username: 'admin', password: isMock ? 'admin' : 'DemoPass!2026', captcha: '', remember: false })
const signupForm = reactive({ username: '', email: '', password: '', confirmPassword: '' })

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }, { minLength: 4, message: '密码不少于 4 位', trigger: 'blur' }],
  captcha: [
    { required: true, message: '请输入验证码', trigger: 'blur' },
    { validator: (value) => new Promise((res, rej) => { if (!value) return res(); value !== captchaCode.value ? rej(new Error('验证码错误，请区分大小写')) : res() }), trigger: 'blur' }
  ]
}

const signupRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  email: [{ required: true, message: '请输入邮箱', trigger: 'blur' }, { match: /^[^\s@]+@[^\s@]+\.[^\s@]+$/, message: '邮箱格式不正确', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }, { minLength: 4, message: '密码不少于 4 位', trigger: 'blur' }],
  confirmPassword: [{ required: true, message: '请再次输入密码', trigger: 'blur' }, { validator: (v) => new Promise((res, rej) => { if (!v) return res(); v !== signupForm.password ? rej(new Error('两次密码不一致')) : res() }), trigger: 'blur' }]
}

async function handleFormSubmit() {
  if (loading.value) return
  if (!form.username?.trim()) { Message.warning('请输入用户名'); return }
  if (!form.password || form.password.length < 4) { Message.warning('密码不少于 4 位'); return }
  if (!form.captcha?.trim()) { Message.warning('请输入验证码'); return }
  if (form.captcha !== captchaCode.value) { Message.error('验证码错误'); refreshCaptcha(); return }

  loading.value = true; error.value = ''
  try {
    await login(form.username.trim(), form.password)
    Message.success('登录成功，正在跳转...')
    router.push('/subjects')
  } catch (e) {
    if (e && (e.code === -1 || e.errorCode === 'NETWORK_ERROR')) { error.value = '网络连接异常，请检查后端服务'; Message.error(error.value) }
    else if (e && (e.code === 401 || e.errorCode === 'INVALID_CREDENTIALS')) { error.value = '用户名或密码错误'; Message.error(error.value) }
    else if (e && e.code === 403) { error.value = '当前账号无登录权限'; Message.error(error.value) }
    else { const msg = (e && (e.message || e.msg)) || '登录失败'; error.value = msg; Message.error(msg) }
    refreshCaptcha()
  } finally { loading.value = false }
}

function handleSignup() {
  if (!signupForm.username.trim()) { Message.warning('请输入用户名'); return }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(signupForm.email)) { Message.warning('请输入正确的邮箱'); return }
  if (!signupForm.password || signupForm.password.length < 4) { Message.warning('密码不少于 4 位'); return }
  if (signupForm.password !== signupForm.confirmPassword) { Message.warning('两次密码不一致'); return }
  Message.success('注册成功！请使用新账号登录')
  isSignUp.value = false
  form.username = signupForm.username
  signupForm.username = signupForm.email = signupForm.password = signupForm.confirmPassword = ''
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  position: relative;
  overflow: hidden;
  background: linear-gradient(135deg, #0e2b7c 0%, #165dff 35%, #4080ff 65%, #e8f3ff 100%);
}

.bg-decor {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

.bg-grid {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  opacity: 0.8;
}

.blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(60px);
  opacity: 0.5;
  animation: floatBlob 14s ease-in-out infinite;
}

.blob-1 {
  width: 420px; height: 420px;
  background: radial-gradient(circle, #4080ff 0%, transparent 70%);
  top: -120px; left: -80px;
}
.blob-2 {
  width: 360px; height: 360px;
  background: radial-gradient(circle, #1e3aa8 0%, transparent 70%);
  bottom: -100px; right: -60px;
  animation-delay: -5s;
}
.blob-3 {
  width: 240px; height: 240px;
  background: radial-gradient(circle, rgba(255,255,255,0.35) 0%, transparent 70%);
  top: 40%; left: 55%;
  animation-delay: -9s;
}

@keyframes floatBlob {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(30px, -20px) scale(1.05); }
  66% { transform: translate(-20px, 25px) scale(0.95); }
}

.deco-ring {
  position: absolute;
  border-radius: 50%;
  border: 1.5px dashed rgba(255, 255, 255, 0.18);
  animation: spin 40s linear infinite;
}
.ring-a { width: 500px; height: 500px; top: -100px; right: -150px; }
.ring-b { width: 350px; height: 350px; bottom: -80px; left: -100px; animation-direction: reverse; animation-duration: 30s; }

@keyframes spin { to { transform: rotate(360deg); } }

.deco-dot {
  position: absolute;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.5);
  box-shadow: 0 0 20px rgba(255,255,255,0.4);
  animation: pulseDot 3s ease-in-out infinite;
}
.dot-1 { width: 8px; height: 8px; top: 22%; right: 18%; animation-delay: 0s; }
.dot-2 { width: 5px; height: 5px; top: 65%; left: 12%; animation-delay: -1s; }
.dot-3 { width: 10px; height: 10px; bottom: 25%; right: 30%; animation-delay: -2s; }

@keyframes pulseDot {
  0%, 100% { opacity: 0.4; transform: scale(1); }
  50% { opacity: 0.9; transform: scale(1.4); }
}

.deco-wave {
  position: absolute;
  bottom: 0;
  left: 0;
  width: 100%;
  height: 120px;
}

.page-main {
  position: relative;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 80px);
  padding: 30px 20px;
}

.login-shell {
  width: 100%;
  max-width: 980px;
}

.login-card {
  background: #fff;
  border-radius: 24px;
  box-shadow: 0 24px 80px rgba(12, 40, 130, 0.25), 0 6px 30px rgba(0,0,0,0.08);
  display: grid;
  grid-template-columns: 1fr 1fr;
  overflow: hidden;
  position: relative;
  min-height: 560px;
  transition: grid-template-columns 0.8s cubic-bezier(0.4, 0, 0.2, 1);
}

.form-side {
  position: relative;
  overflow: hidden;
}

.form-slide {
  position: absolute;
  inset: 0;
  padding: 44px 48px;
  display: flex;
  flex-direction: column;
  transition: opacity 0.7s ease, transform 0.7s cubic-bezier(0.4, 0, 0.2, 1);
  overflow-y: auto;
}

.sign-up-slide {
  opacity: 0;
  transform: translateX(40px);
  pointer-events: none;
}

.login-card.swap-panels .sign-in-slide {
  opacity: 0;
  transform: translateX(-40px);
  pointer-events: none;
}

.login-card.swap-panels .sign-up-slide {
  opacity: 1;
  transform: translateX(0);
  pointer-events: auto;
}

.form-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 20px;
}

.mini-logo { width: 28px; height: 28px; }
.mini-brand { font-size: 15px; font-weight: 600; color: #1d2129; }

.form-title {
  font-size: 30px;
  font-weight: 700;
  line-height: 1.3;
  color: #1d2129;
  margin: 0 0 18px;
  letter-spacing: -0.5px;
}

.brand-hl {
  background: linear-gradient(135deg, #165dff 0%, #4080ff 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.social-row {
  display: flex;
  gap: 12px;
  margin-bottom: 14px;
}

.social-btn {
  width: 42px; height: 42px;
  border-radius: 50%;
  border: 1.5px solid #e5e6eb;
  background: #fff;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer;
  transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s;
}

.social-btn:hover {
  transform: translateY(-2px);
  border-color: #4080ff;
  box-shadow: 0 6px 18px rgba(22, 93, 255, 0.18);
}

.social-btn svg { width: 18px; height: 18px; }

.divider {
  text-align: center;
  position: relative;
  margin: 16px 0 18px;
}
.divider::before {
  content: '';
  position: absolute;
  top: 50%; left: 0; right: 0;
  height: 1px; background: #eef0f4;
}
.divider span {
  background: #fff;
  padding: 0 14px;
  font-size: 12px;
  color: #c9cdd4;
  position: relative;
}

.auth-form { display: flex; flex-direction: column; }

.auth-input :deep(.arco-input-wrapper),
.auth-input :deep(.arco-input-password-wrapper) {
  border-radius: 10px;
  border-color: #e5e6eb;
  background: #f7f9fc;
  transition: all 0.2s;
}
.auth-input :deep(.arco-input-wrapper:hover),
.auth-input :deep(.arco-input-password-wrapper:hover) { border-color: #4080ff; background: #fff; }
.auth-input :deep(.arco-input-wrapper-focused),
.auth-input :deep(.arco-input-password-wrapper-focused) {
  border-color: #165dff !important; background: #fff;
  box-shadow: 0 0 0 3px rgba(22, 93, 255, 0.12);
}

.in-ico { font-size: 16px; color: #86909c; }

.captcha-row { display: flex; gap: 10px; }
.captcha-input { flex: 1; min-width: 0; }
.captcha-canvas {
  flex: none; height: 40px;
  border: 1px solid #e5e6eb;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.captcha-canvas:hover { border-color: #165dff; box-shadow: 0 0 0 2px rgba(22, 93, 255, 0.1); }

.err-alert {
  display: flex; align-items: center; gap: 6px;
  padding: 10px 14px;
  background: #fff2f0; border: 1px solid #ffccc7;
  border-radius: 10px; color: #f53f3f; font-size: 13px; margin-bottom: 16px;
}

.form-options {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 20px; font-size: 13px;
}

.forgot-link { font-size: 13px; }

.btn-primary {
  height: 48px;
  border: none; border-radius: 12px;
  background: linear-gradient(135deg, #165dff 0%, #4080ff 100%);
  color: #fff; font-size: 15px; font-weight: 600;
  letter-spacing: 1.5px;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s, opacity 0.2s;
  display: flex; align-items: center; justify-content: center; gap: 8px;
}

.btn-primary:hover:not(:disabled) {
  box-shadow: 0 8px 24px rgba(22, 93, 255, 0.4);
  transform: translateY(-1px);
}
.btn-primary:active:not(:disabled) { transform: translateY(0); }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }

.btn-spinner {
  width: 16px; height: 16px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

.form-footer-info {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  margin-top: 20px;
}
.mode-hint { font-size: 12px; color: #c9cdd4; }

.brand-side {
  position: relative;
  background: linear-gradient(135deg, #0e3a9a 0%, #165dff 50%, #2b6fff 100%);
  display: flex; align-items: center; justify-content: center;
  overflow: hidden;
}

.brand-slide {
  position: absolute;
  inset: 0;
  padding: 40px 48px;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center;
  color: #fff;
  transition: opacity 0.7s ease, transform 0.7s cubic-bezier(0.4, 0, 0.2, 1);
  z-index: 2;
}

.welcome-slide { opacity: 0; transform: translateX(40px); pointer-events: none; }
.login-card.swap-panels .welcome-slide { opacity: 1; transform: translateX(0); pointer-events: auto; }

.friend-slide { opacity: 1; transform: translateX(0); }
.login-card.swap-panels .friend-slide { opacity: 0; transform: translateX(-40px); pointer-events: none; }

.brand-h1 {
  font-size: 32px; font-weight: 700;
  margin: 0 0 14px; letter-spacing: -0.5px;
  text-shadow: 0 2px 12px rgba(0,0,0,0.15);
}

.brand-desc {
  font-size: 14px; line-height: 1.7;
  margin: 0 0 22px;
  max-width: 320px;
  color: rgba(255,255,255,0.88);
}

.brand-features {
  display: flex; flex-direction: column; gap: 10px;
  margin-bottom: 22px; width: 100%; max-width: 300px;
}
.bf-item {
  display: flex; align-items: center; gap: 8px;
  padding: 9px 14px;
  background: rgba(255,255,255,0.12);
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 10px;
  font-size: 13px; font-weight: 500;
  backdrop-filter: blur(4px);
  text-align: left;
}

.btn-ghost {
  padding: 12px 44px;
  border: 2px solid #fff;
  border-radius: 30px;
  background: transparent;
  color: #fff;
  font-size: 14px; font-weight: 600;
  letter-spacing: 1.5px;
  cursor: pointer;
  transition: all 0.25s;
}
.btn-ghost:hover { background: rgba(255,255,255,0.18); transform: translateY(-1px); }

.brand-pattern {
  position: absolute;
  bottom: -60px; right: -60px;
  width: 320px; height: 320px;
  opacity: 0.7;
  z-index: 1;
  pointer-events: none;
  animation: spin 60s linear infinite;
}

.brand-pattern svg { width: 100%; height: 100%; }

.page-footer {
  position: relative;
  z-index: 2;
  padding: 18px 40px;
  text-align: center;
  font-size: 12px;
  color: rgba(255,255,255,0.75);
}

.forgot-content { padding: 12px 16px 0; text-align: center; }
.forgot-icon { font-size: 48px; color: #165dff; margin-bottom: 14px; }
.forgot-text { margin: 0 0 6px; font-size: 14px; color: #1d2129; }
.forgot-contact { margin: 0 0 24px; font-size: 13px; color: #86909c; }

@media (max-width: 768px) {
  .login-card { grid-template-columns: 1fr; max-width: 420px; }
  .brand-side { display: none; }
  .form-slide { padding: 32px 28px; }
  .form-title { font-size: 26px; }
}

@media (max-width: 480px) {
  .page-main { padding: 16px; }
  .form-slide { padding: 24px 18px; }
  .blob, .deco-ring { display: none; }
}
</style>