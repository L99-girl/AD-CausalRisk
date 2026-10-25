import request from './request.js'
import { MOCK_SUBJECTS, MOCK_VISITS, mockDelay } from '../mock/data.js'

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

export async function getSubjectList(params = {}) {
  const { page = 1, pageSize = 10 } = params
  if (USE_MOCK) {
    await mockDelay(400)
    const start = (page - 1) * pageSize
    const items = MOCK_SUBJECTS.slice(start, start + pageSize)
    return { items, total: MOCK_SUBJECTS.length, page, pageSize }
  }
  return request.get('/subjects', { params: { page, pageSize } })
}

export async function getSubjectDetail(id) {
  if (USE_MOCK) {
    await mockDelay(200)
    const s = MOCK_SUBJECTS.find(x => x.id === Number(id))
    if (!s) {
      return Promise.reject({ code: 404, errorCode: 'NOT_FOUND', message: '档案不存在' })
    }
    return { subject: s, visits: MOCK_VISITS[id] || [], features: [] }
  }
  return request.get(`/subjects/${id}`)
}

export async function createSubject(data) {
  if (USE_MOCK) {
    await mockDelay(300)
    const newItem = {
      id: Date.now(),
      subjectCode: data.subjectCode,
      alias: data.alias,
      status: 'ACTIVE',
      dataVersion: 'demo-local-' + Date.now(),
      createdAt: new Date().toISOString()
    }
    return newItem
  }
  return request.post('/subjects', { subjectCode: data.subjectCode, alias: data.alias })
}

export async function addVisit(subjectId, data) {
  if (USE_MOCK) {
    await mockDelay(300)
    const list = MOCK_VISITS[subjectId] || (MOCK_VISITS[subjectId] = [])
    const newVisit = {
      id: Date.now(),
      visitCode: data.visitCode || `V${subjectId}-${list.length + 1}`,
      visitDate: data.visitDate || new Date().toISOString(),
      mmse: data.mmse ?? null,
      moca: data.moca ?? null,
      cdrSb: data.cdrSb ?? null
    }
    list.push(newVisit)
    return newVisit
  }
  return request.post(`/subjects/${subjectId}/visits`, data)
}

export async function updateSubject(id, data) {
  if (USE_MOCK) {
    await mockDelay(300)
    const idx = MOCK_SUBJECTS.findIndex(x => x.id === Number(id))
    if (idx === -1) {
      return Promise.reject({ code: 404, errorCode: 'NOT_FOUND', message: '档案不存在' })
    }
    MOCK_SUBJECTS[idx] = { ...MOCK_SUBJECTS[idx], ...data, id: Number(id) }
    return MOCK_SUBJECTS[idx]
  }
  return Promise.reject({
    code: 501,
    errorCode: 'NOT_IMPLEMENTED',
    message: '后端暂未实现档案编辑接口，请联系后端开发'
  })
}