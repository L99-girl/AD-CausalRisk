import request from './request.js'

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

function mockRows() {
  return [
    { id: 1, subjectId: 101, visitId: 1, subjectCode: 'SUB-1001', subjectAlias: '张伟', visitCode: 'V1', targetType: 'SUBJECT', sourceType: 'QC', status: 'PENDING', abnormalItems: 'MMSE 分值异常', auditComment: '', auditorName: '', createdAt: new Date().toISOString() },
    { id: 2, subjectId: 102, visitId: 2, subjectCode: 'SUB-1002', subjectAlias: '李娜', visitCode: 'V2', targetType: 'VISIT', sourceType: 'QC', status: 'APPROVED', abnormalItems: '血液标志物缺失', auditComment: '已核对原始数据', auditorName: '研究员甲', createdAt: new Date().toISOString() }
  ]
}

export async function getQcList(params = {}) {
  const { page = 1, pageSize = 10, status } = params
  if (USE_MOCK) {
    let items = mockRows()
    if (status) items = items.filter(r => r.status === status)
    return { items: items.slice((page - 1) * pageSize, page * pageSize), total: items.length, page, pageSize }
  }
  return request.get('/qc/list', { params: { page, pageSize, status } })
}

export async function getQcStats() {
  if (USE_MOCK) {
    const rows = mockRows()
    return {
      pendingCount: rows.filter(r => r.status === 'PENDING').length,
      approvedCount: rows.filter(r => r.status === 'APPROVED').length,
      rejectedCount: rows.filter(r => r.status === 'REJECTED').length
    }
  }
  return request.get('/qc/stats')
}

export async function submitAudit(id, data = {}) {
  if (USE_MOCK) {
    const row = mockRows().find(r => r.id === Number(id)) || {}
    return { ...row, status: data.status, auditComment: data.auditComment, auditorName: '当前用户' }
  }
  return request.post(`/qc/${id}/audit`, data)
}