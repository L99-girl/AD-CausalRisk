<template>
  <div class="page">
    <a-card :bordered="false" class="import-card">
      <template #title>
        <div class="card-header">
          <div class="card-title">
            <div class="title-badge">
              <icon-upload class="title-icon" />
            </div>
            CSV 档案导入
          </div>
          <span class="card-subtitle">批量导入受试者档案数据</span>
        </div>
      </template>
      <template #extra>
        <a-button class="template-btn" @click="downloadSample">
          <icon-download /> 下载模板
        </a-button>
      </template>

      <div class="import-body">
        <a-alert type="info" :closable="false" class="tip-alert" show-icon>
          <template #title>
            <a-space :size="16">
              <span> 流程：选择文件 → 上传解析 → 预览校验 → 确认入库</span>
              <a-tag color="arcoblue" size="small">当前 Mock 模式</a-tag>
            </a-space>
          </template>
        </a-alert>

        <div class="stepper">
          <div
            v-for="(step, i) in steps"
            :key="i"
            class="step-item"
            :class="{ done: currentStep > i, active: currentStep === i }"
          >
            <div class="step-dot">
              <icon-check-circle v-if="currentStep > i" />
              <span v-else>{{ i + 1 }}</span>
            </div>
            <span class="step-label">{{ step }}</span>
            <div v-if="i < steps.length - 1" class="step-line" />
          </div>
        </div>

        <div class="upload-section">
          <a-upload
            v-model:file-list="fileList"
            :auto-upload="false"
            :limit="1"
            accept=".csv"
            drag
            class="csv-dragger"
            :disabled="isUploading || isPreviewing || isCommitting"
            @change="onFileChange"
            @remove="onFileRemove"
          >
            <div class="drag-inner">
              <div class="drag-icon-wrap">
                <icon-upload class="drag-icon" />
              </div>
              <div class="drag-text">
                <span class="drag-main">点击或拖拽 CSV 文件到此区域</span>
                <span class="drag-sub">支持 .csv 格式，最大 10MB，UTF-8 编码</span>
              </div>
            </div>
          </a-upload>
        </div>

        <div v-if="fileList.length > 0" class="file-info">
          <div class="file-row">
            <div class="file-left">
              <div class="file-icon-wrap">
                <icon-file class="file-icon" />
              </div>
              <div class="file-meta">
                <div class="file-name">{{ currentFile?.name }}</div>
                <div class="file-size">{{ formatSize(currentFile?.size) }} · 已就绪</div>
              </div>
            </div>
            <a-button
              v-if="!isUploading && !isPreviewing && !isCommitting"
              type="text"
              status="danger"
              size="small"
              @click="clearFile"
            >
              <icon-delete /> 移除
            </a-button>
          </div>

          <div v-if="isUploading || uploadProgress > 0" class="progress-block">
            <div class="progress-label">
              <span><icon-upload /> 上传中</span>
              <span class="progress-val">{{ uploadProgress }}%</span>
            </div>
            <a-progress :percent="uploadProgress" :status="isUploading ? undefined : 'success'" :show-text="false" size="medium" />
          </div>

          <div v-if="previewProgress > 0" class="progress-block">
            <div class="progress-label">
              <span><icon-search /> 解析与校验</span>
              <span class="progress-val">{{ previewProgress }}%</span>
            </div>
            <a-progress :percent="previewProgress" :status="isPreviewing ? undefined : 'success'" :show-text="false" size="medium" />
          </div>

          <div v-if="commitProgress > 0" class="progress-block">
            <div class="progress-label">
              <span><icon-check-circle /> 提交入库</span>
              <span class="progress-val">{{ commitProgress }}%</span>
            </div>
            <a-progress :percent="commitProgress" :status="isCommitting ? undefined : 'success'" :show-text="false" size="medium" />
          </div>
        </div>

        <a-alert v-if="errorMsg" type="error" :message="errorMsg" show-icon class="alert-error" />

        <template v-if="previewResult">
          <a-alert
            :type="previewResult.status === 'BLOCKED' ? 'error' : previewResult.invalidRows > 0 ? 'warning' : 'success'"
            class="result-alert"
            show-icon
          >
            <template #title>
              <div class="result-alert-head">
                <strong class="result-title">
                  {{ previewResult.status === 'BLOCKED' ? '⚠️ 导入已拦截' : previewResult.invalidRows > 0 ? '🔍 校验完成，存在异常' : '✅ 校验通过，可以导入' }}
                </strong>
                <a-tag :color="previewResult.status === 'BLOCKED' ? 'red' : previewResult.invalidRows > 0 ? 'orange' : 'green'" size="small">
                  {{ previewResult.dataVersion }}
                </a-tag>
              </div>
            </template>
            <div class="result-stats">
              <div class="stat-item total"><div class="stat-num">{{ previewResult.totalRows }}</div><div class="stat-label">总行数</div></div>
              <div class="stat-item ok"><div class="stat-num">{{ previewResult.validRows }}</div><div class="stat-label">可导入</div></div>
              <div class="stat-item bad"><div class="stat-num">{{ previewResult.invalidRows }}</div><div class="stat-label">异常</div></div>
            </div>
          </a-alert>

          <div v-if="previewResult.errorRows.length > 0" class="error-panel">
            <div class="error-head">
              <span class="error-title"><icon-exclamation /> 异常明细（{{ previewResult.errorRows.length }} 条）</span>
              <a-tag color="orange" size="small">仅预览</a-tag>
            </div>
            <a-table
              :data="previewResult.errorRows"
              :pagination="{ pageSize: 5, showTotal: true, sizeCanChange: false }"
              :bordered="false"
              size="small"
              row-key="rowNumber"
              stripe
              :scroll="{ y: 240 }"
            >
              <template #columns>
                <a-table-column title="行号" data-index="rowNumber" width="80" :align="true">
                  <template #cell="{ record }"><span class="row-num">第 {{ record.rowNumber }} 行</span></template>
                </a-table-column>
                <a-table-column title="编号" data-index="subjectCode" width="160" />
                <a-table-column title="别名" data-index="alias" width="130" />
                <a-table-column title="级别" data-index="severity" width="90" :align="true">
                  <template #cell="{ record }">
                    <a-tag :color="record.severity === 'ERROR' ? 'red' : 'orange'" size="small">
                      {{ record.severity === 'ERROR' ? '错误' : '警告' }}
                    </a-tag>
                  </template>
                </a-table-column>
                <a-table-column title="问题">
                  <template #cell="{ record }">
                    <div class="issues-wrap">
                      <a-tag
                        v-for="(iss, idx) in record.issues"
                        :key="idx"
                        :color="record.severity === 'ERROR' ? 'red' : 'orange'"
                        size="small"
                        :bordered="false"
                        class="issue-tag"
                      >{{ iss }}</a-tag>
                    </div>
                  </template>
                </a-table-column>
              </template>
            </a-table>
          </div>

          <div v-if="!commitResult" class="commit-area">
            <a-space :size="12">
              <a-button
                type="primary"
                size="large"
                :loading="isCommitting"
                :disabled="previewResult.status === 'BLOCKED' || isCommitting"
                @click="doCommit"
              >
                <template #icon><icon-check-circle /></template>
                {{ isCommitting ? '提交中…' : `确认导入 ${previewResult.validRows} 条` }}
              </a-button>
              <a-button size="large" @click="resetAll">
                <template #icon><icon-refresh /></template>
                重新上传
              </a-button>
            </a-space>
            <a-alert
              v-if="previewResult.status === 'BLOCKED'"
              type="error"
              :closable="false"
              class="blocked-alert"
              show-icon
            >
              异常数据占比过高，无法提交。请修正 CSV 后重新上传。
            </a-alert>
          </div>
        </template>

        <template v-if="commitResult">
          <a-alert type="success" class="result-alert success-alert" show-icon>
            <template #title>
              <div class="result-alert-head">
                <strong class="result-title">✅ 导入完成</strong>
                <a-tag color="green" size="small">{{ commitResult.jobId }}</a-tag>
              </div>
            </template>
            <div class="result-stats">
              <div class="stat-item ok"><div class="stat-num">{{ previewResult.validRows }}</div><div class="stat-label">成功入库</div></div>
              <div v-if="previewResult.invalidRows > 0" class="stat-item bad"><div class="stat-num">{{ previewResult.invalidRows }}</div><div class="stat-label">异常已跳过</div></div>
              <div class="stat-item total"><div class="stat-num">{{ previewResult.totalRows }}</div><div class="stat-label">总计</div></div>
            </div>
          </a-alert>

          <div class="result-actions">
            <a-space :size="12">
              <a-button type="primary" @click="goSubjects"><icon-user-group /> 返回档案列表</a-button>
              <a-button @click="resetAll"><icon-plus /> 继续导入</a-button>
            </a-space>
          </div>
        </template>
      </div>
    </a-card>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import {
  IconUpload, IconDownload, IconDelete, IconSearch,
  IconCheckCircle, IconRefresh, IconFile, IconExclamation,
  IconUserGroup, IconPlus
} from '@arco-design/web-vue/es/icon'
import { validateCsvFile, previewImport, commitImport } from '../api/import.js'
import { mockDelay } from '../mock/data.js'

const router = useRouter()

const steps = ['选择文件', '上传解析', '预览校验', '确认入库']
const currentStep = ref(0)

const fileList = ref([])
const currentFile = computed(() => fileList.value[0]?.originFileObj || null)

const isUploading = ref(false)
const uploadProgress = ref(0)

const isPreviewing = ref(false)
const previewProgress = ref(0)
const previewResult = ref(null)
const errorMsg = ref('')

const isCommitting = ref(false)
const commitProgress = ref(0)
const commitResult = ref(null)

function onFileChange(info) {
  errorMsg.value = ''
  previewResult.value = null
  commitResult.value = null
  const f = info.file
  if (!f || !f.name) return
  const v = validateCsvFile(f)
  if (!v.ok) {
    errorMsg.value = v.reason
    fileList.value = []
    Message.error(v.reason)
    return
  }
  currentStep.value = 1
  simulateUpload()
}

function onFileRemove() { resetAll() }

function clearFile() { fileList.value = []; resetAll() }

function resetAll() {
  fileList.value = []
  previewResult.value = null
  commitResult.value = null
  errorMsg.value = ''
  uploadProgress.value = 0
  previewProgress.value = 0
  commitProgress.value = 0
  isUploading.value = false
  isPreviewing.value = false
  isCommitting.value = false
  currentStep.value = 0
}

function formatSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(2) + ' MB'
}

function simulateUpload() {
  isUploading.value = true
  uploadProgress.value = 0
  let p = 0
  const timer = setInterval(async () => {
    p += Math.random() * 15 + 5
    if (p >= 100) {
      uploadProgress.value = 100
      isUploading.value = false
      currentStep.value = 2
      clearInterval(timer)
      await mockDelay(200)
      doPreview()
    } else {
      uploadProgress.value = Math.round(p)
    }
  }, 120)
}

async function doPreview() {
  if (!currentFile.value) return
  isPreviewing.value = true
  previewProgress.value = 0
  previewResult.value = null
  errorMsg.value = ''
  try {
    const res = await previewImport(currentFile.value, (p) => { previewProgress.value = p })
    previewResult.value = res
    Message.success(res.invalidRows > 0
      ? `校验完成：${res.validRows} 条可导入，${res.invalidRows} 条异常`
      : `校验通过：${res.validRows} 条档案可导入`
    )
  } catch (e) {
    errorMsg.value = e.message || '解析失败'
    Message.error(errorMsg.value)
  } finally {
    isPreviewing.value = false
  }
}

async function doCommit() {
  if (!previewResult.value) return
  isCommitting.value = true
  commitProgress.value = 0
  currentStep.value = 3
  let p = 0
  const timer = setInterval(() => {
    p += Math.random() * 20 + 8
    if (p >= 100) { p = 100; commitProgress.value = 100; clearInterval(timer) }
    else commitProgress.value = Math.round(p)
  }, 100)
  try {
    const res = await commitImport(previewResult.value.jobId, () => {})
    commitResult.value = res
    Message.success('导入任务已完成')
  } catch (e) {
    Message.error(e.message || '提交失败')
  } finally {
    isCommitting.value = false
    clearInterval(timer)
    commitProgress.value = 100
  }
}

function goSubjects() { router.push('/subjects') }

function downloadSample() {
  const lines = [
    '# ============================================================',
    '# AD-CausalRisk 档案导入模板',
    '# 字段说明：',
    '#   subject_code   编号（必填，格式 DEMO-XXX）',
    '#   alias          姓名/别名（必填）',
    '#   gender         性别（M/F）',
    '#   age            年龄（整数）',
    '#   apoe           APOE 基因型（E2/E3/E4 组合）',
    '#   diagnosis      诊断（AD / MCI / Normal）',
    '#   data_version   数据版本（demo-vX.X）',
    '# ============================================================',
    'subject_code,alias,gender,age,apoe,diagnosis,data_version',
    'DEMO-TMPL-001,张三,M,65,E3/E4,AD,demo-v1.0',
    'DEMO-TMPL-002,李四,F,70,E3/E3,MCI,demo-v1.0',
    'DEMO-TMPL-003,王五,M,58,E2/E3,Normal,demo-v1.1',
    'DEMO-TMPL-004,赵六,F,74,E4/E4,AD,demo-v1.0',
    'DEMO-TMPL-005,钱七,M,61,E3/E4,MCI,demo-v1.1'
  ]
  const csv = '\ufeff' + lines.join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `subjects_import_template_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
  Message.success('模板已下载')
}
</script>

<style scoped>
.page { padding: 20px 24px 40px; }
.import-card { border-radius: 12px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.06); border: none; }

.card-header { display: flex; align-items: center; gap: 14px; }
.card-title { font-size: 16px; font-weight: 600; color: var(--color-text-1); display: flex; align-items: center; gap: 10px; }
.title-badge { width: 32px; height: 32px; border-radius: 8px; background: linear-gradient(135deg, #165DFF 0%, #722ED1 100%); display: flex; align-items: center; justify-content: center; color: #fff; }
.title-icon { font-size: 16px; }
.card-subtitle { font-size: 12px; color: var(--color-text-3); }
.template-btn { border-radius: 8px; }

.import-body { padding: 4px 0; }
.tip-alert { margin-bottom: 24px; border-radius: 10px; }

.stepper { display: flex; align-items: center; justify-content: center; margin-bottom: 28px; padding: 0 20px; }
.step-item { display: flex; align-items: center; gap: 10px; position: relative; }
.step-dot { width: 28px; height: 28px; border-radius: 50%; background: var(--color-fill-2); border: 2px solid var(--color-border-3); display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 600; color: var(--color-text-3); transition: all 0.3s; }
.step-item.done .step-dot { background: var(--color-primary-light-2); border-color: var(--color-primary-6); color: #fff; font-size: 16px; }
.step-item.active .step-dot { background: var(--color-primary-6); border-color: var(--color-primary-6); color: #fff; box-shadow: 0 0 0 4px var(--color-primary-light-2); }
.step-label { font-size: 13px; color: var(--color-text-3); min-width: 56px; }
.step-item.done .step-label { color: var(--color-text-1); }
.step-item.active .step-label { color: var(--color-primary-6); font-weight: 500; }
.step-line { width: 60px; height: 2px; background: var(--color-border-3); margin: 0 12px; margin-bottom: 14px; }
.step-item.done .step-line { background: var(--color-primary-6); }

.csv-dragger :deep(.arco-upload-drag) { border-radius: 12px; border: 2px dashed var(--color-border-3); background: var(--color-fill-2); padding: 24px 0; transition: all 0.25s; }
.csv-dragger :deep(.arco-upload-drag:hover) { border-color: var(--color-primary-6); background: var(--color-primary-light-1); transform: translateY(-1px); }

.drag-inner { display: flex; align-items: center; justify-content: center; gap: 24px; padding: 8px 0; }
.drag-icon-wrap { width: 64px; height: 64px; border-radius: 16px; background: linear-gradient(135deg, rgba(22, 93, 255, 0.12) 0%, rgba(114, 46, 209, 0.12) 100%); display: flex; align-items: center; justify-content: center; }
.drag-icon { font-size: 32px; color: var(--color-primary-6); }
.drag-text { display: flex; flex-direction: column; gap: 6px; }
.drag-main { font-size: 15px; color: var(--color-text-1); font-weight: 500; }
.drag-sub { font-size: 12px; color: var(--color-text-3); }

.file-info { margin-top: 20px; padding: 18px 20px; background: var(--color-fill-2); border-radius: 12px; border: 1px solid var(--color-border-2); }
.file-row { display: flex; justify-content: space-between; align-items: center; }
.file-left { display: flex; align-items: center; gap: 14px; }
.file-icon-wrap { width: 44px; height: 44px; border-radius: 10px; background: linear-gradient(135deg, #10b981 0%, #059669 100%); display: flex; align-items: center; justify-content: center; color: #fff; }
.file-icon { font-size: 22px; }
.file-meta { display: flex; flex-direction: column; gap: 2px; }
.file-name { font-size: 14px; font-weight: 500; color: var(--color-text-1); }
.file-size { font-size: 12px; color: var(--color-text-3); }

.progress-block { margin-top: 14px; padding: 12px 16px; background: var(--color-bg-2); border-radius: 8px; border: 1px solid var(--color-border-2); }
.progress-label { display: flex; justify-content: space-between; align-items: center; font-size: 13px; color: var(--color-text-2); margin-bottom: 8px; font-weight: 500; }
.progress-label span:first-child { display: flex; align-items: center; gap: 6px; }
.progress-val { color: var(--color-primary-6); font-weight: 600; }

.alert-error { margin-top: 16px; border-radius: 10px; }

.result-alert { margin-top: 20px; border-radius: 10px; padding: 16px 20px; }
.result-alert-head { display: flex; justify-content: space-between; align-items: center; }
.result-title { font-size: 14px; }
.result-stats { display: flex; gap: 32px; margin-top: 14px; }
.stat-item { display: flex; flex-direction: column; gap: 4px; }
.stat-num { font-size: 26px; font-weight: 700; font-family: 'SF Mono', Consolas, monospace; line-height: 1; }
.stat-label { font-size: 12px; color: var(--color-text-3); }
.stat-item.total .stat-num { color: var(--color-text-1); }
.stat-item.ok .stat-num { color: #00b42a; }
.stat-item.bad .stat-num { color: #f53f3f; }

.error-panel { margin-top: 20px; border: 1px solid var(--color-border-2); border-radius: 12px; overflow: hidden; background: var(--color-bg-2); }
.error-head { display: flex; justify-content: space-between; align-items: center; padding: 12px 18px; background: var(--color-fill-2); border-bottom: 1px solid var(--color-border-2); }
.error-title { font-size: 13px; font-weight: 600; color: var(--color-text-1); display: flex; align-items: center; gap: 6px; }
.row-num { color: var(--color-text-3); font-size: 12px; }
.issues-wrap { display: flex; flex-wrap: wrap; gap: 4px; }
.issue-tag { font-size: 12px; }

.commit-area { margin-top: 22px; display: flex; flex-direction: column; gap: 14px; }
.blocked-alert { border-radius: 8px; }

.success-alert { padding-bottom: 20px; }
.result-actions { margin-top: 16px; }
</style>