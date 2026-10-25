import { defineStore } from 'pinia'

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'
const PERSIST_KEY = USE_MOCK ? 'ad-causalrisk-user-mock' : 'ad-causalrisk-user-live'

export const useUserStore = defineStore('user', {
  state: () => ({
    username: '',
    roles: [],
    permissions: []
  }),

  getters: {
    isLoggedIn: (state) => !!state.username,
    hasRole: (state) => (role) => {
      if (!role) return true
      const need = Array.isArray(role) ? role : [role]
      return need.some(r => state.roles.includes(r))
    },
    hasPermission: (state) => (perm) => {
      if (!perm) return true
      const need = Array.isArray(perm) ? perm : [perm]
      return need.some(p => state.permissions.includes(p))
    }
  },

  actions: {
    setUser({ username, roles = [], permissions = [] }) {
      this.username = username
      this.roles = roles
      this.permissions = permissions
    },
    logout() {
      this.username = ''
      this.roles = []
      this.permissions = []
    },
    loginAsDemo(role = 'admin') {
      const DEMO_ACCOUNTS = {
        admin: { username: 'admin', roles: ['ADMIN'], permissions: ['*'] },
        researcher: { username: 'researcher', roles: ['RESEARCHER'], permissions: ['subject:list', 'subject:import'] },
        doctor: { username: 'doctor', roles: ['DOCTOR'], permissions: ['subject:list'] },
        patient: { username: 'patient', roles: ['PATIENT'], permissions: [] }
      }
      const acc = DEMO_ACCOUNTS[role] || DEMO_ACCOUNTS.admin
      this.setUser(acc)
    }
  },

  persist: {
    key: PERSIST_KEY,
    pick: ['username', 'roles', 'permissions']
  }
})