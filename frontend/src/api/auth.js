import request from './request.js'
import { mockDelay } from '../mock/data.js'
import { useUserStore } from '../stores/user.js'

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

export async function login(username, password) {
  if (USE_MOCK) {
    await mockDelay(300)
    if (username === 'admin' && password === 'admin') {
      localStorage.setItem('token', 'mock-token-' + Date.now())
      const store = useUserStore()
      store.setUser({
        username,
        roles: ['ADMIN'],
        permissions: []
      })
      return { username, roles: ['ADMIN'] }
    }
    return Promise.reject({ code: 401, errorCode: 'INVALID_CREDENTIALS', message: '用户名或密码错误' })
  }
  const data = await request.post('/auth/login', { username, password })
  const store = useUserStore()
  store.setUser({
    username: data.username,
    roles: data.roles || [],
    permissions: []
  })
  return data
}

export async function logout() {
  localStorage.removeItem('token')
  const store = useUserStore()
  store.logout()
  if (!USE_MOCK) {
    try {
      await request.post('/auth/logout')
    } catch (_) {}
  }
}

export function isLoggedIn() {
  if (USE_MOCK) {
    return !!localStorage.getItem('token')
  }
  const store = useUserStore()
  return store.isLoggedIn
}