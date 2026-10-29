import request from './request.js'
import { mockDelay } from '../mock/data.js'

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'

// 后端 Idempotency-Key 用于去重幂等；每次上传生成一个唯一值
function newIdempotencyKey() {
  return `imp-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

const PRESET_ISSUES = {
  'DEMO-ERR-001': ['subject_code 重复', 'APOE 基因型格式错误'],
  'DEMO-ERR-002': ['风险分超出 [0,1] 范围'],
  'DEMO-ERR-003': ['必填字段 diagnosis 缺失'],
  'DEMO-ERR-004': ['subject_code 违反格式 DEMO-XXX']
}

function parseCsv(content) {
  const lines = content.trim().split(/\r?\n/)
  const header = lines[0].split(',').map(h => h.trim())
  const rows = []
  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(',')
    if (cols.length < 2) continue
    const obj = {}
    header.forEach((h, idx) => { obj[h] = (cols[idx] || '').trim() })
    rows.push(obj)
  }
  return { header, rows }
}

function genMockImportResult(file) {
  const totalRows = 18 + Math.floor(Math.random() * 30)
  const invalidRows = Math.floor(totalRows * (0.05 + Math.random() * 0.15))
  const validRows = totalRows - invalidRows

  const errorRows = []
  for (let i = 0; i < invalidRows; i++) {
    const code = Object.keys(PRESET_ISSUES)[i % Object.keys(PRESET_ISSUES).length]
    errorRows.push({
      rowNumber: 2 + Math.floor(Math.random() * totalRows),
      subjectCode: code,
      alias: `错误记录 ${i + 1}`,
      issues: PRESET_ISSUES[code],
      severity: Math.random() > 0.5 ? 'ERROR' : 'WARN'
    })
  }

  return {
    jobId: 'JOB-' + Date.now(),
    fileName: file.name,
    dataVersion: 'demo-v' + (1 + Math.floor(Math.random() * 2)) + '.' + Math.floor(Math.random() * 3),
    status: invalidRows > totalRows * 0.2 ? 'BLOCKED' : 'PREVIEW_READY',
    totalRows,
    validRows,
    invalidRows,
    errorRows,
    startedAt: new Date().toISOString(),
    estimatedCommitDelayMs: 800
  }
}

export function validateCsvFile(file) {
  const ALLOWED_EXTS = ['.csv']
  const MAX_SIZE_MB = 10
  const lower = file.name.toLowerCase()
  const okExt = ALLOWED_EXTS.some(ext => lower.endsWith(ext))
  if (!okExt) return { ok: false, reason: '仅支持 .csv 格式' }
  if (file.size > MAX_SIZE_MB * 1024 * 1024) return { ok: false, reason: `文件超过 ${MAX_SIZE_MB}MB` }
  return { ok: true }
}

export async function previewImport(file, onProgress) {
  if (!USE_MOCK) {
    const fd = new FormData()
    fd.append('file', file)
    // 对齐后端 POST /api/import-jobs，multipart/form-data（axios 对 FormData 自动设 boundary 并加 Content-Type），携带幂等键
    return request.post('/import-jobs', fd, {
      headers: { 'Idempotency-Key': newIdempotencyKey() }
    })
  }
  const totalSteps = 25
  for (let i = 1; i <= totalSteps; i++) {
    await mockDelay(40 + Math.random() * 60)
    onProgress?.(Math.round((i / totalSteps) * 100))
  }
  return genMockImportResult(file)
}

export async function commitImport(jobId, onProgress) {
  if (!USE_MOCK) {
    // 对齐后端 POST /api/import-jobs/{jobId}/commit
    return request.post(`/import-jobs/${jobId}/commit`)
  }
  for (let i = 1; i <= 10; i++) {
    await mockDelay(60 + Math.random() * 80)
    onProgress?.(i * 10)
  }
  return {
    jobId,
    status: 'COMMITTED',
    committedAt: new Date().toISOString()
  }
}