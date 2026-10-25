import axios from 'axios'

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

const request = axios.create({
  baseURL: '/api',
  timeout: 10000,
  withCredentials: !USE_MOCK
})

request.interceptors.request.use(config => {
  if (USE_MOCK) {
    const token = localStorage.getItem('token')
    if (token) config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

request.interceptors.response.use(
  response => {
    const payload = response.data
    if (payload && typeof payload === 'object' && 'code' in payload) {
      if (payload.code !== 0) {
        return Promise.reject({
          code: payload.code,
          errorCode: payload.errorCode,
          message: payload.message || '请求失败'
        })
      }
      return payload.data
    }
    return payload
  },
  error => {
    if (!error.response) {
      return Promise.reject({
        code: -1,
        errorCode: 'NETWORK_ERROR',
        message: '网络连接异常，请检查后端服务是否启动'
      })
    }
    const body = error.response.data || {}
    return Promise.reject({
      code: body.code || error.response.status,
      errorCode: body.errorCode,
      message: body.message || error.message || '请求失败'
    })
  }
)

export default request