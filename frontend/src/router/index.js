import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '../stores/user.js'

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

const routes = [
  {
    path: '/login',
    name: 'Login',
    // 3D 炫酷登录页（队友代码）；旧版 Login.vue 保留备用，稳定后再删
    component: () => import('../views/LoginView.vue'),
    meta: { title: '登录', noLayout: true }
  },
  {
    path: '/401',
    name: 'Exception401',
    component: () => import('../views/exception/401.vue'),
    meta: { title: '无权限', noLayout: true }
  },
  {
    path: '/500',
    name: 'Exception500',
    component: () => import('../views/exception/500.vue'),
    meta: { title: '服务器错误', noLayout: true }
  },
  {
    path: '/',
    component: () => import('../layout/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('../views/Dashboard.vue'),
        meta: { title: '首页', keepAlive: true }
      },
      {
        path: 'subjects',
        name: 'SubjectList',
        component: () => import('../views/SubjectList.vue'),
        meta: { title: '档案列表', keepAlive: true }
      },
      {
        path: 'subjects/import',
        name: 'SubjectImport',
        component: () => import('../views/SubjectImport.vue'),
        meta: { title: 'CSV 导入' }
      },
      {
        path: 'qc',
        name: 'QcAuditList',
        component: () => import('../views/qc/QcAuditList.vue'),
        meta: { title: '质控审核', keepAlive: true, roles: ['ADMIN', 'RESEARCHER'] }
      }
    ]
  },
  {
    path: '/doctor',
    name: 'DoctorHome',
    component: () => import('../views/RolePlaceholder.vue'),
    meta: { title: '医生工作台', role: '医生', noLayout: true }
  },
  {
    path: '/researcher',
    name: 'ResearcherHome',
    component: () => import('../views/RolePlaceholder.vue'),
    meta: { title: '科研人员工作台', role: '科研人员', noLayout: true }
  },
  {
    path: '/admin',
    name: 'AdminHome',
    component: () => import('../views/RolePlaceholder.vue'),
    meta: { title: '管理员工作台', role: '管理员', noLayout: true }
  },
  {
    path: '/patient',
    name: 'PatientHome',
    component: () => import('../views/RolePlaceholder.vue'),
    meta: { title: '患者工作台', role: '患者', noLayout: true }
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'Exception404',
    component: () => import('../views/exception/404.vue'),
    meta: { title: '页面不存在', noLayout: true }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, _from, next) => {
  if (to.meta?.title) {
    document.title = `${to.meta.title} · AD-CausalRisk`
  } else {
    document.title = 'AD-CausalRisk · 因果风险评估平台'
  }

  const userStore = useUserStore()
  const publicPaths = ['/login', '/401', '/500', '/404']

  if (!USE_MOCK && !userStore.isLoggedIn && !publicPaths.includes(to.path)) {
    return next('/login')
  }
  if (!USE_MOCK && userStore.isLoggedIn && to.path === '/login') {
    return next('/')
  }

  next()
})

export default router