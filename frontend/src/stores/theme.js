import { defineStore } from 'pinia'
import { watch } from 'vue'

const DARK_ATTR = 'arco-theme'
const VALID_SIZES = ['small', 'medium', 'large']

function applyDark(isDark) {
  if (isDark) {
    document.body.setAttribute(DARK_ATTR, 'dark')
  } else {
    document.body.removeAttribute(DARK_ATTR)
  }
}

function applySize(size) {
  document.body.setAttribute('arco-size', size)
  const root = document.documentElement
  if (size === 'small') root.style.fontSize = '13px'
  else if (size === 'large') root.style.fontSize = '15px'
  else root.style.fontSize = '14px'
}

const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')

export const useThemeStore = defineStore('theme', {
  state: () => ({
    isDark: false,
    size: 'medium'
  }),

  actions: {
    toggleDark() { this.isDark = !this.isDark },
    setDark(val) { this.isDark = !!val },
    setSize(size) { if (VALID_SIZES.includes(size)) this.size = size },
    initFromSystem() { this.isDark = mediaQuery.matches }
  },

  persist: {
    key: 'ad-causalrisk-theme',
    pick: ['isDark', 'size']
  }
})

watch(
  () => { try { return useThemeStore().isDark } catch { return null } },
  (val) => { if (val !== null) applyDark(val) }
)
watch(
  () => { try { return useThemeStore().size } catch { return null } },
  (val) => { if (val) applySize(val) }
)

if (document.readyState !== 'loading') {
  try {
    const s = useThemeStore()
    applyDark(s.isDark)
    applySize(s.size)
  } catch {}
}