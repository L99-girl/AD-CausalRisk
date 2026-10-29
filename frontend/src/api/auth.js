import request from './request.js'
import { mockDelay } from '../mock/data.js'
import { useUserStore } from '../stores/user.js'

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

export async function login(username, password) {
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