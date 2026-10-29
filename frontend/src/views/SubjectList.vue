<template>
  <div class="page">
    <a-row :gutter="16" class="stat-row">
      <a-col :xs="12" :sm="8" :md="6" v-for="s in stats" :key="s.key">
        <a-card :bordered="false" class="stat-card" :class="'stat-' + s.key">
          <a-statistic :value="s.value" :title="s.label">
            <template #prefix>
              <component :is="s.icon" />
            </template>
          </a-statistic>
        </a-card>
      </a-col>
    </a-row>

    <a-card :bordered="false" class="toolbar-card">
      <div class="toolbar">
        <div class="toolbar-left">
          <a-button v-permission="['ADMIN', 'RESEARCHER']" type="primary" @click="handleAdd">
            <template #icon><icon-plus /></template>
            新增
          </a-button>
          <a-tooltip content="后端暂未支持删除" position="bottom">
            <a-button :disabled="true" status="danger">
              <template #icon><icon-delete /></template>
              删除
            </a-button>
          </a-tooltip>
          <a-divider direction="vertical" />
          <a-button disabled>
            <template #icon><icon-download /></template>
            导出
          </a-button>
          <a-button disabled>
            <template #icon><icon-upload /></template>
            导入
          </a-button>
        </div>
        <div class="toolbar-right">
          <a-input-search
            v-model="keyword"
            placeholder="搜索编号 / 姓名"
            style="width: 260px"
            :allow-clear="true"
            @search="fetchList"
            @clear="fetchList"
          />
          <a-select
            v-model="filterQuality"
            placeholder="质量状态"
            style="width: 130px"
            allow-clear
            @change="fetchList"
          >
            <a-option value="PASS">PASS</a-option>
            <a-option value="WARN">WARN</a-option>
            <a-option value="BLOCKED">BLOCKED</a-option>
          </a-select>
          <a-select
            v-model="filterDiagnosis"
            placeholder="诊断"
            style="width: 120px"
            allow-clear
            @change="fetchList"
          >
            <a-option value="AD">AD</a-option>
            <a-option value="MCI">MCI</a-option>
            <a-option value="Normal">Normal</a-option>
          </a-select>
          <a-tooltip content="重置筛选">
            <a-button type="text" @click="resetFilters">
              <template #icon><icon-refresh /></template>
            </a-button>
          </a-tooltip>
        </div>
      </div>
    </a-card>

    <a-card :bordered="false" class="main-split-card">
      <div class="split-layout">
        <div class="tree-panel">
          <div class="tree-header">
            <span class="tree-title">档案分组</span>
            <a-dropdown>
              <a-button type="text" size="mini">
                <icon-settings />
              </a-button>
              <template #content>
                <a-doption disabled>新建分组</a-doption>
                <a-doption disabled>管理分组</a-doption>
              </template>
            </a-dropdown>
          </div>
          <a-tree
            :data="treeData"
            :selected-keys="selectedGroup"
            :default-expand-all="true"
            :show-line="true"
            @select="onTreeSelect"
            class="group-tree"
          >
            <template #title="{ title, key }">
              <span class="tree-node-title">
                <icon-folder v-if="!String(key).startsWith('leaf-')" class="node-icon" />
                <icon-file v-else class="node-icon leaf" />
                {{ title }}
              </span>
            </template>
          </a-tree>
        </div>

        <div class="table-panel">
          <div class="table-head">
            <a-space>
              <span class="card-title">档案数据</span>
              <a-tag color="arcoblue" size="small">{{ totalFiltered }} 条记录</a-tag>
              <a-tag v-if="selectedRowKeys.length" color="green" size="small">
                已选 {{ selectedRowKeys.length }} 项
              </a-tag>
            </a-space>
            <a-space>
              <a-tooltip content="Mock 模式：后端未启动，使用本地假数据">
                <a-tag :color="isMock ? 'orangered' : 'green'" size="small">
                  {{ isMock ? 'Mock' : 'Live' }}
                </a-tag>
              </a-tooltip>
            </a-space>
          </div>

          <a-alert
            v-if="error"
            type="error"
            :message="'加载失败：' + error"
            class="alert-error"
            show-icon
          />

          <a-table
            :data="pagedList"
            :loading="loading"
            :bordered="false"
            size="medium"
            row-key="id"
            stripe
            :row-selection="rowSelection"
            :row-class-name="rowClassName"
            @row-click="onRowClick"
            class="subject-table"
          >
            <template #columns>
              <a-table-column title="序号" :width="70" align="center">
                <template #cell="{ rowIndex }">
                  {{ (pagination.current - 1) * pagination.pageSize + rowIndex + 1 }}
                </template>
              </a-table-column>

              <a-table-column title="编号" :width="150">
                <template #cell="{ record }">
                  <a-link class="code-link" @click.stop="handleDetail(record)">
                    {{ record.subjectCode }}
                  </a-link>
                </template>
              </a-table-column>

              <a-table-column title="别名" :width="130">
                <template #cell="{ record }">
                  {{ record.alias || '—' }}
                </template>
              </a-table-column>

              <a-table-column title="状态" :width="100" align="center">
                <template #cell="{ record }">
                  <a-tag :color="record.status === 'ACTIVE' ? 'green' : 'gray'" size="small">
                    {{ record.status === 'ACTIVE' ? '启用' : '已归档' }}
                  </a-tag>
                </template>
              </a-table-column>

              <a-table-column title="建档时间" :width="180">
                <template #cell="{ record }">
                  {{ record.createdAt ? formatDate(record.createdAt) : '—' }}
                </template>
              </a-table-column>

              <a-table-column title="操作" :width="160" align="center">
                <template #cell="{ record }">
                  <a-space :size="6" class="action-links">
                    <a-link @click.stop="handleDetail(record)">详情</a-link>
                    <a-link status="warning" @click.stop="handleEdit(record)">编辑</a-link>
                    <a-tooltip content="后端暂未支持删除" position="bottom">
                      <span class="disabled-link">删除</span>
                    </a-tooltip>
                  </a-space>
                </template>
              </a-table-column>
            </template>
          </a-table>

          <div class="pagination-wrap">
            <a-pagination
              v-model:current="pagination.current"
              v-model:page-size="pagination.pageSize"
              :total="totalFiltered"
              :show-total="true"
              :show-jumper="true"
              :show-page-size="true"
              :page-size-changeable="pageSizeOptions"
              size-can-change
            />
          </div>
        </div>
      </div>
    </a-card>

    <a-modal
      v-model:visible="addVisible"
      title="新增档案"
      :ok-loading="addLoading"
      ok-text="确认创建"
      cancel-text="取消"
      :mask-closable="false"
      :unmount-on-close="true"
      @ok="submitAdd"
    >
      <a-form
        ref="addFormRef"
        :model="addForm"
        layout="vertical"
        :auto-label-width="false"
      >
        <a-form-item
          field="subjectCode"
          label="档案编号"
          :rules="[{ required: true, message: '请输入档案编号' }]"
        >
          <a-input
            v-model="addForm.subjectCode"
            placeholder="DEMO-XXX（建议 DEMO- 开头）"
            allow-clear
            :max-length="64"
          />
        </a-form-item>
        <a-form-item
          field="alias"
          label="别名"
          :rules="[{ required: true, message: '请输入别名' }]"
        >
          <a-input
            v-model="addForm.alias"
            placeholder="患者姓名或研究代号"
            allow-clear
            :max-length="128"
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <a-modal
      v-model:visible="addVisitVisible"
      title="新增访视"
      :ok-loading="addVisitLoading"
      ok-text="确认提交"
      cancel-text="取消"
      :mask-closable="false"
      :unmount-on-close="true"
      @ok="submitAddVisit"
    >
      <a-form
        ref="addVisitFormRef"
        :model="addVisitForm"
        layout="vertical"
        :auto-label-width="false"
      >
        <a-form-item
          field="visitCode"
          label="访视编号"
          :rules="[{ required: true, message: '请输入访视编号' }]"
        >
          <a-input
            v-model="addVisitForm.visitCode"
            placeholder="例如 V001-03"
            allow-clear
            :max-length="64"
          />
        </a-form-item>
        <a-form-item field="visitDate" label="访视日期">
          <a-date-picker
            v-model="addVisitForm.visitDate"
            placeholder="选择日期"
            style="width: 100%"
          />
        </a-form-item>
        <a-row :gutter="12">
          <a-col :span="8">
            <a-form-item field="mmse" label="MMSE">
              <a-input-number
                v-model="addVisitForm.mmse"
                :min="0"
                placeholder="常规范围 0-30"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item field="moca" label="MoCA">
              <a-input-number
                v-model="addVisitForm.moca"
                :min="0"
                placeholder="常规范围 0-30"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
          <a-col :span="8">
            <a-form-item field="cdrSb" label="CDR-SB">
              <a-input-number
                v-model="addVisitForm.cdrSb"
                :min="0"
                :step="0.5"
                placeholder="常规范围 0-18"
                style="width: 100%"
              />
            </a-form-item>
          </a-col>
        </a-row>
      </a-form>
    </a-modal>

    <a-modal
      v-model:visible="detailVisible"
      title="档案详情"
      :width="560"
      :footer="false"
      :unmount-on-close="true"
    >
      <div v-if="detailLoading" class="detail-loading">
        <a-spin /> 加载中…
      </div>
      <template v-else-if="detailData">
        <a-descriptions :column="1" bordered size="small" class="detail-desc">
          <a-descriptions-item label="编号">
            <span class="mono">{{ detailData.subject.subjectCode }}</span>
          </a-descriptions-item>
          <a-descriptions-item label="别名">{{ detailData.subject.alias }}</a-descriptions-item>
          <a-descriptions-item label="状态">
            <a-tag :color="detailData.subject.status === 'ACTIVE' ? 'green' : 'gray'" size="small">
              {{ detailData.subject.status === 'ACTIVE' ? '启用' : '已归档' }}
            </a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="数据版本">
            v{{ detailData.subject.dataVersion ?? '—' }}
          </a-descriptions-item>
          <a-descriptions-item label="建档时间">
            {{ detailData.subject.createdAt ? formatDate(detailData.subject.createdAt) : '—' }}
          </a-descriptions-item>
        </a-descriptions>

        <a-divider class="detail-divider" />

        <div class="detail-section">
          <div class="section-title-row">
            <span class="section-title">访视记录</span>
            <a-button type="primary" size="small" @click="handleOpenAddVisit">
              <template #icon><icon-plus /></template>
              新增访视
            </a-button>
          </div>
          <template v-if="detailData.visits?.length">
            <a-table
              :data="detailData.visits"
              :pagination="false"
              size="small"
              :bordered="false"
              row-key="id"
            >
              <template #columns>
                <a-table-column title="访视编号" data-index="visitCode" :width="110">
                  <template #cell="{ record }">
                    <span class="mono">{{ record.visitCode || '—' }}</span>
                  </template>
                </a-table-column>
                <a-table-column title="访视日期" :width="160">
                  <template #cell="{ record }">{{ record.visitDate ? formatDate(record.visitDate) : '—' }}</template>
                </a-table-column>
                <a-table-column title="MMSE" :width="80" align="center">
                  <template #cell="{ record }">{{ record.mmse ?? '—' }}</template>
                </a-table-column>
                <a-table-column title="MoCA" :width="80" align="center">
                  <template #cell="{ record }">{{ record.moca ?? '—' }}</template>
                </a-table-column>
                <a-table-column title="CDR-SB" :width="90" align="center">
                  <template #cell="{ record }">{{ record.cdrSb ?? '—' }}</template>
                </a-table-column>
              </template>
            </a-table>
          </template>
          <a-empty v-else description="暂无访视记录" :image-style="{ height: 60 }" />
        </div>

        <div class="detail-section">
          <div class="section-title">特征数据</div>
          <template v-if="detailData.features?.length">
            <a-table
              :data="detailData.features"
              :pagination="false"
              size="small"
              :bordered="false"
              row-key="id"
            >
              <template #columns>
                <a-table-column title="ID" data-index="id" :width="60" />
                <a-table-column title="特征名称" data-index="featureName" />
                <a-table-column title="值" data-index="featureValue" />
              </template>
            </a-table>
          </template>
          <a-empty v-else description="暂无特征数据" :image-style="{ height: 60 }" />
        </div>
      </template>
    </a-modal>
  </div>
</template>

<script setup>
import { ref, computed, reactive, onMounted, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { Message } from '@arco-design/web-vue'
import {
  IconUser, IconHeart, IconCloseCircle, IconCheckCircle,
  IconPlus, IconDelete, IconDownload, IconUpload, IconRefresh,
  IconFolder, IconFile, IconSettings, IconCheck, IconExclamation
} from '@arco-design/web-vue/es/icon'
import { getSubjectList, createSubject, getSubjectDetail, addVisit } from '../api/subject.js'

const router = useRouter()

const list = ref([])
const loading = ref(false)
const error = ref('')
const keyword = ref('')
const filterQuality = ref('')
const filterDiagnosis = ref('')
const selectedGroup = ref(['all'])
const selectedRowKeys = ref([])
const totalCount = ref(0)

const isMock = computed(() => import.meta.env.VITE_USE_MOCK !== 'false')

const pageSizeOptions = [10, 20, 50, 100]

const pagination = reactive({ current: 1, pageSize: 10 })

const qualityColor = { PASS: 'green', WARN: 'orange', BLOCKED: 'red' }

function qualityIcon(q) {
  const map = { PASS: '✓', WARN: '!', BLOCKED: '✕' }
  return map[q] || ''
}
function qualityTooltip(q) {
  const map = {
    PASS: '质量检查通过，可参与风险评估',
    WARN: '存在轻度异常，建议复核',
    BLOCKED: '质量严重不达标，无法参与评估'
  }
  return map[q] || q
}
function diagnosisColor(d) {
  return { AD: 'red', MCI: 'orange', Normal: 'green' }[d] || 'gray'
}

function riskLevel(v) {
  if (v >= 0.8) return 'high'
  if (v >= 0.6) return 'mid'
  return 'low'
}
function riskProgressColor(v) {
  if (v >= 0.8) return '#f53f3f'
  if (v >= 0.6) return '#ff7d00'
  return '#00b42a'
}

const stats = computed(() => {
  const all = list.value
  return [
    { key: 'total', label: '受试者总数', value: isMock.value ? all.length : totalCount.value, icon: IconUser },
    { key: 'pass',  label: '质量通过',  value: all.filter(x => x.qualityStatus === 'PASS').length, icon: IconCheckCircle },
    { key: 'warn',  label: '质量警告',  value: all.filter(x => x.qualityStatus === 'WARN').length, icon: IconExclamation },
    { key: 'block', label: '质量拦截',  value: all.filter(x => x.qualityStatus === 'BLOCKED').length, icon: IconCloseCircle }
  ]
})

const treeData = ref([
  {
    key: 'all', title: '全部档案',
    children: [
      { key: 'leaf-ad',   title: 'AD 患者',  isLeaf: true },
      { key: 'leaf-mci',  title: 'MCI 人群', isLeaf: true },
      { key: 'leaf-norm', title: '正常对照', isLeaf: true }
    ]
  },
  {
    key: 'qc', title: '按质量分组',
    children: [
      { key: 'leaf-pass',  title: 'PASS（通过）',  isLeaf: true },
      { key: 'leaf-warn',  title: 'WARN（警告）',  isLeaf: true },
      { key: 'leaf-block', title: 'BLOCKED（拦截）', isLeaf: true }
    ]
  }
])

function onTreeSelect(key) {
  selectedGroup.value = key
  pagination.current = 1
  fetchList()
}


const rowSelection = computed(() => ({
  selectedRowKeys: selectedRowKeys.value,
  onChange: (keys) => { selectedRowKeys.value = keys }
}))

function rowClassName(record) {
  if (record.qualityStatus === 'BLOCKED') return 'row-blocked'
  if (record.qualityStatus === 'WARN') return 'row-warn'
  return ''
}
function onRowClick(record) {
  console.log('row click', record.subjectCode)
}

const filteredList = computed(() => {
  if (!isMock.value) return list.value
  let data = list.value
  if (keyword.value) {
    const k = keyword.value.toLowerCase()
    data = data.filter(x =>
      x.subjectCode.toLowerCase().includes(k) ||
      (x.alias || '').toLowerCase().includes(k)
    )
  }
  if (filterQuality.value) data = data.filter(x => x.qualityStatus === filterQuality.value)
  if (filterDiagnosis.value) data = data.filter(x => x.diagnosis === filterDiagnosis.value)
  const groupKey = selectedGroup.value?.[0]
  if (groupKey && !['all', 'qc'].includes(groupKey)) {
    const map = {
      'leaf-ad': r => r.diagnosis === 'AD',
      'leaf-mci': r => r.diagnosis === 'MCI',
      'leaf-norm': r => r.diagnosis === 'Normal',
      'leaf-pass': r => r.qualityStatus === 'PASS',
      'leaf-warn': r => r.qualityStatus === 'WARN',
      'leaf-block': r => r.qualityStatus === 'BLOCKED'
    }
    const fn = map[groupKey]
    if (fn) data = data.filter(fn)
  }
  return data
})

const totalFiltered = computed(() => {
  if (!isMock.value) return totalCount.value
  return filteredList.value.length
})

const pagedList = computed(() => {
  if (!isMock.value) return list.value
  const start = (pagination.current - 1) * pagination.pageSize
  return filteredList.value.slice(start, start + pagination.pageSize)
})

async function fetchList() {
  loading.value = true
  error.value = ''
  try {
    const data = await getSubjectList({ page: pagination.current, pageSize: pagination.pageSize })
    list.value = data.items || []
    totalCount.value = data.total ?? 0
    if (isMock.value) {
      pagination.current = 1
    }
  } catch (e) {
    error.value = e.message || '未知错误'
  } finally {
    loading.value = false
  }
}

watch(() => [pagination.current, pagination.pageSize], () => {
  fetchList()
})

function resetFilters() {
  keyword.value = ''
  filterQuality.value = ''
  filterDiagnosis.value = ''
  pagination.current = 1
  fetchList()
}

function formatDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const addVisible = ref(false)
const addLoading = ref(false)
const addFormRef = ref(null)
const addForm = reactive({ subjectCode: '', alias: '' })

function handleAdd() {
  addForm.subjectCode = ''
  addForm.alias = ''
  addVisible.value = true
}

async function submitAdd() {
  if (!addFormRef.value) return
  try {
    await addFormRef.value.validate()
  } catch (_) {
    return false
  }
  addLoading.value = true
  try {
    await createSubject({ subjectCode: addForm.subjectCode.trim(), alias: addForm.alias.trim() })
    Message.success('创建成功')
    addVisible.value = false
    fetchList()
    return true
  } catch (e) {
    Message.error(e.message || '创建失败')
    return false
  } finally {
    addLoading.value = false
  }
}

const detailVisible = ref(false)
const detailLoading = ref(false)
const detailData = ref(null)

const addVisitVisible = ref(false)
const addVisitLoading = ref(false)
const addVisitFormRef = ref(null)
const addVisitForm = reactive({
  visitCode: '',
  visitDate: '',
  mmse: null,
  moca: null,
  cdrSb: null
})

function resetAddVisitForm() {
  addVisitForm.visitCode = ''
  addVisitForm.visitDate = ''
  addVisitForm.mmse = null
  addVisitForm.moca = null
  addVisitForm.cdrSb = null
  addVisitFormRef.value?.resetFields()
}

function handleOpenAddVisit() {
  resetAddVisitForm()
  addVisitVisible.value = true
}

async function submitAddVisit() {
  if (!addVisitFormRef.value || !detailData.value?.subject) return
  try {
    await addVisitFormRef.value.validate()
  } catch (_) {
    return false
  }
  addVisitLoading.value = true
  try {
    const payload = {
      visitCode: addVisitForm.visitCode.trim(),
      visitDate: addVisitForm.visitDate
        ? (addVisitForm.visitDate instanceof Date
            ? addVisitForm.visitDate.toISOString()
            : String(addVisitForm.visitDate))
        : null,
      mmse: addVisitForm.mmse ?? null,
      moca: addVisitForm.moca ?? null,
      cdrSb: addVisitForm.cdrSb ?? null
    }
    await addVisit(detailData.value.subject.id, payload)
    Message.success('新增访视成功')
    addVisitVisible.value = false
    const subjectId = detailData.value.subject.id
    detailData.value = await getSubjectDetail(subjectId)
    return true
  } catch (e) {
    Message.error(e.message || '新增访视失败')
    return false
  } finally {
    addVisitLoading.value = false
  }
}

async function handleDetail(record) {
  detailData.value = null
  detailLoading.value = true
  detailVisible.value = true
  try {
    detailData.value = await getSubjectDetail(record.id)
  } catch (e) {
    detailVisible.value = false
    if (e.errorCode === 'VALIDATION_ERROR') {
      Message.error('档案不存在')
    } else if (e.code === 403 || e.errorCode === 'ACCESS_DENIED') {
      Message.error('无权限查看此档案')
    } else {
      Message.error(e.message || '加载详情失败')
    }
  } finally {
    detailLoading.value = false
  }
}

function handleEdit(record) {
  Message.warning(`编辑 ${record.subjectCode} — 功能开发中`)
}

onMounted(fetchList)
</script>

<style scoped>
.page {
  padding: 20px 16px 40px;
  min-height: calc(100vh - 56px);
  /* 背景由 MainLayout.content 的蓝紫渐变下沉提供，这里透明透出。
     仅叠加两层亮色光晕，增强本页的玻璃反射层次。 */
  background:
    radial-gradient(820px 420px at 85% 0%, rgba(191, 219, 254, 0.35), transparent 60%),
    radial-gradient(700px 380px at 5% 100%, rgba(224, 231, 255, 0.35), transparent 55%);
}

/* ===================== 毛玻璃通用段落（后续可复用） ===================== */
.glass-card {
  background: rgba(255, 255, 255, 0.45) !important;
  -webkit-backdrop-filter: blur(14px);
  backdrop-filter: blur(14px);
  border: 1px solid rgba(255, 255, 255, 0.6);
  border-top: 1px solid rgba(255, 255, 255, 0.85);
  border-left: 1px solid rgba(255, 255, 255, 0.85);
  box-shadow: 0 8px 32px rgba(0, 100, 255, 0.1) !important;
  border-radius: 16px;
}

/* Arco <a-card> 内层默认白底兜底置透明，避免盖住玻璃质感 */
.stat-card :deep(.arco-card),
.toolbar-card :deep(.arco-card),
.main-split-card :deep(.arco-card) {
  background: transparent;
  border: none;
  box-shadow: none;
}

.stat-row { margin-bottom: 16px; }
.stat-card {
  background: rgba(255, 255, 255, 0.45) !important;
  -webkit-backdrop-filter: blur(14px);
  backdrop-filter: blur(14px);
  border: 1px solid rgba(255, 255, 255, 0.6);
  border-top: 1px solid rgba(255, 255, 255, 0.85);
  border-left: 1px solid rgba(255, 255, 255, 0.85);
  box-shadow: 0 8px 32px rgba(0, 100, 255, 0.1) !important;
  border-radius: 16px;
  overflow: hidden;
  transition: transform 0.2s, box-shadow 0.2s;
}
.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 34px rgba(0, 0, 0, 0.09);
}
.stat-card :deep(.arco-card-body) { padding: 18px 20px; }
.stat-card :deep(.arco-statistic-title) {
  font-size: 13px; color: var(--color-text-3); margin-bottom: 6px;
}
.stat-card :deep(.arco-statistic-value) { font-size: 26px; font-weight: 600; }
.stat-total :deep(.arco-statistic-value) { color: #165DFF; }
.stat-pass  :deep(.arco-statistic-value) { color: #00b42a; }
.stat-warn  :deep(.arco-statistic-value) { color: #ff7d00; }
.stat-block :deep(.arco-statistic-value) { color: #f53f3f; }

.toolbar-card {
  background: rgba(255, 255, 255, 0.45) !important;
  -webkit-backdrop-filter: blur(14px);
  backdrop-filter: blur(14px);
  border: 1px solid rgba(255, 255, 255, 0.6);
  border-top: 1px solid rgba(255, 255, 255, 0.85);
  border-left: 1px solid rgba(255, 255, 255, 0.85);
  box-shadow: 0 8px 32px rgba(0, 100, 255, 0.1) !important;
  border-radius: 16px;
  margin-bottom: 16px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.toolbar-left, .toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.main-split-card {
  background: rgba(255, 255, 255, 0.45) !important;
  -webkit-backdrop-filter: blur(14px);
  backdrop-filter: blur(14px);
  border: 1px solid rgba(255, 255, 255, 0.6);
  border-top: 1px solid rgba(255, 255, 255, 0.85);
  border-left: 1px solid rgba(255, 255, 255, 0.85);
  box-shadow: 0 8px 32px rgba(0, 100, 255, 0.1) !important;
  border-radius: 16px;
  overflow: hidden;
}

.split-layout { display: flex; gap: 0; min-height: 520px; }

.tree-panel {
  width: 240px;
  flex-shrink: 0;
  border-right: 1px solid rgba(255, 255, 255, 0.5);
  padding: 0 12px 12px;
  background: rgba(240, 248, 255, 0.35);
}

.tree-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 8px; border-bottom: 1px solid rgba(255, 255, 255, 0.6); margin-bottom: 8px;
}
.tree-title { font-size: 13px; font-weight: 600; color: var(--color-text-1); }

.group-tree { padding: 4px 0; }
.group-tree :deep(.arco-tree),
.group-tree :deep(.arco-tree-node) { background: transparent !important; }
.group-tree :deep(.arco-tree-node-title) { border-radius: 6px; padding: 2px 6px; }
.group-tree :deep(.arco-tree-node-selected .arco-tree-node-title) {
  background: var(--color-primary-light-2); color: var(--color-primary-6);
}
.tree-node-title { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }
.node-icon { color: #ff7d00; font-size: 14px; }
.node-icon.leaf { color: #165DFF; }

.table-panel { flex: 1; padding: 0; display: flex; flex-direction: column; }

.table-head {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 18px; border-bottom: 1px solid rgba(255, 255, 255, 0.6);
}
.card-title { font-size: 15px; font-weight: 600; color: var(--color-text-1); }

/* ===== 暴力穿透：表格与树的所有顽固白底清成透明 ===== */
.subject-table :deep(.arco-table),
.subject-table :deep(.arco-table-container),
.subject-table :deep(.arco-table-body),
.subject-table :deep(.arco-table-tr),
.subject-table :deep(.arco-table-th),
.subject-table :deep(.arco-table-td),
.group-tree :deep(.arco-tree),
.group-tree :deep(.arco-tree-node) {
  background-color: transparent !important;
}
/* 表头增加一点点底色区分 */
.subject-table :deep(.arco-table-th) {
  background-color: rgba(255, 255, 255, 0.4) !important;
  font-weight: 600;
  color: var(--color-text-1);
}

/* 表格透明 + 浅蓝表头 + 浅蓝 hover 微光 */
.subject-table { flex: 1; }
.subject-table :deep(.arco-table-container),
.subject-table :deep(.arco-table),
.subject-table :deep(.arco-table-tr),
.subject-table :deep(.arco-table-content) { background: transparent; }
.subject-table :deep(.arco-table-td-row) { background: transparent; }
.subject-table :deep(.arco-table-body) { background: transparent; }
.subject-table :deep(.arco-table-td) {
  background: transparent !important;
  border-bottom-color: rgba(255, 255, 255, 0.5);
}
.subject-table :deep(.arco-table-tbody > tr) {
  transition: background-color 0.18s ease;
}
.subject-table :deep(.arco-table-tbody > tr:hover > td) {
  background: rgba(186, 225, 255, 0.35) !important;
  box-shadow: inset 0 0 0 1px rgba(122, 190, 240, 0.18);
}
.subject-table :deep(.arco-table-tbody > tr.row-warn > td) {
  background: rgba(255, 125, 0, 0.06);
}
.subject-table :deep(.arco-table-tbody > tr.row-warn:hover > td) {
  background: rgba(255, 125, 0, 0.12);
}
.subject-table :deep(.arco-table-tbody > tr.row-blocked > td) {
  background: rgba(245, 63, 63, 0.05);
}
.subject-table :deep(.arco-table-tbody > tr.row-blocked:hover > td) {
  background: rgba(245, 63, 63, 0.10);
}
/* 斑马纹静音，避免遮盖玻璃质感 */
.subject-table :deep(.arco-table-tr-striped .arco-table-td) {
  background: rgba(240, 248, 255, 0.28) !important;
}

.idx-num { color: var(--color-text-3); font-family: Menlo, Monaco, Consolas, monospace; font-size: 13px; }

.code-link {
  font-family: Menlo, Monaco, Consolas, monospace;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
}

.cell-na { color: var(--color-text-4); }

.risk-cell {
  display: flex; align-items: center; gap: 8px;
}
.risk-text { font-size: 13px; font-weight: 600; min-width: 46px; }
.risk-text.risk-high { color: #f53f3f; }
.risk-text.risk-mid  { color: #ff7d00; }
.risk-text.risk-low  { color: #00b42a; }

.q-tag { font-weight: 500; min-width: 80px; text-align: center; letter-spacing: 0.3px; }

.action-links { font-size: 13px; }
.action-links .arco-link { padding: 2px 4px; }
.disabled-link {
  color: var(--color-text-4);
  cursor: not-allowed;
  padding: 2px 4px;
  text-decoration: none;
}

.pagination-wrap {
  display: flex; justify-content: flex-end;
  padding: 14px 18px; border-top: 1px solid rgba(255, 255, 255, 0.6);
}

/* 「新增」主按钮：保留蓝色主色，增加柔和外发光 */
.toolbar-left :deep(.arco-btn-primary) {
  box-shadow: 0 6px 18px rgba(22, 93, 255, 0.28);
}

/* 状态 Tag：半透明背景、去边框、文字保持鲜艳 */
.toolbar-card :deep(.arco-tag),
.main-split-card :deep(.arco-tag) {
  background: rgba(255, 255, 255, 0.5);
  border: none;
  backdrop-filter: blur(4px);
}

.alert-error { margin-bottom: 16px; }

.detail-loading {
  display: flex; align-items: center; justify-content: center;
  padding: 32px 0; color: var(--color-text-3); gap: 10px;
}
.detail-desc :deep(.arco-descriptions-item-label-col) {
  width: 100px;
  font-weight: 500;
}
.detail-divider { margin: 16px 0 12px; }
.detail-section { margin-bottom: 18px; }
.detail-section:last-child { margin-bottom: 0; }
.section-title-row {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 8px;
}
.section-title-row .section-title { margin-bottom: 0; }
.section-title {
  font-size: 13px; font-weight: 600; color: var(--color-text-2);
  padding-left: 8px;
  border-left: 3px solid var(--color-primary-6);
}
.mono { font-family: Menlo, Monaco, Consolas, monospace; }
</style>