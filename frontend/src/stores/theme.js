import { defineStore } from 'pinia'
import { watch } from 'vue'

const VALID_SIZES = ['small', 'medium', 'large']

// The whole app is locked to light mode. Dark mode is intentionally unsupported:
// there is no toggle, no system-following, and any stale dark token is purged on boot.
function purgeDark() {
  document.body.removeAttribute('arco-theme')
  try {
    localStorage.removeItem('ad-causalrisk-theme')
  } catch {}
}

function applySize(size) {
  document.body.setAttribute('arco-size', size)
  const root = document.documentElement
  if (size === 'small') root.style.fontSize = '13px'
  else if (size === 'large') root.style.fontSize = '15px'
  else root.style.fontSize = '14px'
}

export const useThemeStore = defineStore('theme', {
  state: () => ({
    size: 'medium'
  }),

  actions: {
    setSize(size) { if (VALID_SIZES.includes(size)) this.size = size }
  },

  persist: {
    key: 'ad-causalrisk-theme',
    pick: ['size']
  }
})

watch(
  () => { try { return useThemeStore().size } catch { return null } },
  (val) => { if (val) applySize(val) }
)

if (document.readyState !== 'loading') {
  try {
    purgeDark()
    applySize(useThemeStore().size)
  } catch {}
}