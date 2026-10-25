import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'
import ArcoVue from '@arco-design/web-vue'
import '@arco-design/web-vue/dist/arco.css'
import App from './App.vue'
import router from './router'
import { vPermission } from './directives/permission.js'
import { useUserStore } from './stores/user.js'

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

const pinia = createPinia()
pinia.use(piniaPluginPersistedstate)

const app = createApp(App)
app.use(pinia)
app.use(router)
app.use(ArcoVue)

app.directive('permission', vPermission)

const userStore = useUserStore()
if (USE_MOCK && !userStore.isLoggedIn) {
  userStore.loginAsDemo('admin')
}

app.mount('#app')