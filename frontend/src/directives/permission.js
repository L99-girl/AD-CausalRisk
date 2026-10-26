import { useUserStore } from '../stores/user.js'

function check(el, binding) {
  const { value, arg } = binding
  if (!value && !arg) return
  if (value === false || value === null || value === undefined) return

  let required
  if (Array.isArray(value)) {
    required = value
  } else if (typeof value === 'string') {
    required = [value]
  } else if (arg) {
    required = [arg]
  } else {
    return
  }

  const userStore = useUserStore()
  const has = required.some(r => {
    if (r === '*') return true
    if (userStore.roles?.includes(r)) return true
    if (userStore.permissions?.includes(r)) return true
    return false
  })

  if (!has) {
    el.parentNode?.removeChild(el)
  }
}

export const vPermission = {
  mounted(el, binding) { check(el, binding) },
  updated(el, binding) { check(el, binding) }
}