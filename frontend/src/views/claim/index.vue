<template>
  <section class="page" data-module="claim">
    <header class="page-head">
      <div>
        <h2>理赔申请管理</h2>
        <p class="page-desc">提交理赔申请会联动更新保单的理赔次数与结案状态；导出按当前筛选条件取全部命中记录，条数与合计和列表一致。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">提交理赔申请</button>
        <button class="btn" type="button" :disabled="exporting" @click="exportPackage">
          {{ exporting ? '打包中…' : '导出理赔材料包' }}
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>理赔单号 / 保单号 / 事故设备</span>
        <input v-model="filters.keyword" placeholder="关键字检索" />
      </label>
      <label class="filter-item">
        <span>保单号</span>
        <input v-model="filters.policy_no" placeholder="按保单号过滤" />
      </label>
      <label class="filter-item">
        <span>承保单位</span>
        <input v-model="filters.insurer" placeholder="按承保单位过滤" />
      </label>
      <label class="filter-item">
        <span>理赔状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option value="理赔中">理赔中</option>
          <option value="已结案">已结案</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="exportResult || exportError" class="export-panel">
      <div>
        <template v-if="exportResult">
          <span class="success-text">{{ exportResult.message }}</span>
          <div class="material-meta">
            批次 {{ exportResult.batch_id }} · 共 {{ exportResult.total }} 条 · 申请金额合计
            {{ Number(exportResult.total_amount).toFixed(2) }} 元 · 导出时间 {{ exportResult.exported_at }}
          </div>
        </template>
        <span v-else class="error-text">{{ exportError }}</span>
      </div>
      <div class="row-actions">
        <button v-if="exportResult" class="btn primary" type="button" @click="downloadPackage">
          下载材料包（.zip）
        </button>
        <!-- 失败或需要按最新数据重打包时都可以直接重试 -->
        <button class="btn" type="button" :disabled="exporting" @click="exportPackage">
          {{ exporting ? '打包中…' : exportResult ? '重新导出（覆盖旧包）' : '重试导出' }}
        </button>
      </div>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>状态 / 操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <span :class="row.closed ? 'badge badge-closed' : 'badge badge-open'">
              {{ row.closed ? '已结案' : '理赔中' }}
            </span>
            <RouterLink class="link" :to="`/claim/${row.id}`">详情</RouterLink>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">当前条件下暂无理赔申请</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>当前范围共 {{ total }} 条，申请金额合计 {{ summaryAmount }} 元（与材料包口径一致）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="showForm" class="modal-mask" @click.self="showForm = false">
      <div class="modal">
        <div class="modal-head">
          <h3>提交理赔申请</h3>
          <button class="modal-close" type="button" @click="showForm = false">×</button>
        </div>
        <form class="form-grid" @submit.prevent="submitClaim">
          <label><span class="req">保单号</span><input v-model="form.保单号" placeholder="如 INSR-2026-0001" /></label>
          <label><span class="req">事故设备</span><input v-model="form.事故设备" /></label>
          <label><span class="req">出险日期</span><input v-model="form.出险日期" type="date" /></label>
          <label><span class="req">申请金额（元）</span><input v-model="form.申请金额" type="number" min="0" step="0.01" /></label>
          <label class="span-2">申请人<input v-model="form.申请人" placeholder="留空则取保单经办人" /></label>
          <label class="span-2">
            <span class="req">事故经过</span>
            <textarea v-model="form.事故经过" placeholder="简要描述出险情况与理赔诉求"></textarea>
          </label>
        </form>
        <p v-if="formError" class="error-text">{{ formError }}</p>
        <div class="modal-foot">
          <button class="btn" type="button" @click="showForm = false">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitClaim">
            {{ submitting ? '提交中…' : '提交申请' }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type ExportResult = {
  message: string
  batch_id: string
  filename: string
  total: number
  total_amount: number
  exported_at: string
  overwritten: boolean
}

const ENDPOINT = '/api/claim'
const columns = ['理赔单号', '保单号', '承保单位', '事故设备', '出险日期', '申请金额', '申请人', '申请时间', '结案时间', '结案结论']

const rows = ref<Row[]>([])
const total = ref(0)
const summaryAmount = ref('0.00')
const errorMessage = ref('')
const filters = ref<Record<string, string>>({ keyword: '', policy_no: '', insurer: '', status: '' })

const stats = computed(() => [
  { label: '当前范围申请', value: total.value },
  { label: '申请金额合计（元）', value: Number(summaryAmount.value).toLocaleString() },
  { label: '在途（未结案）', value: rows.value.filter((row) => !row.closed).length },
])

const showForm = ref(false)
const submitting = ref(false)
const formError = ref('')
const emptyForm = () => ({ 保单号: '', 事故设备: '', 出险日期: '', 申请金额: '', 申请人: '', 事故经过: '' })
const form = ref(emptyForm())

const exporting = ref(false)
const exportResult = ref<ExportResult | null>(null)
const exportError = ref('')

function openCreate() {
  form.value = emptyForm()
  formError.value = ''
  showForm.value = true
}

async function submitClaim() {
  formError.value = ''
  submitting.value = true
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: form.value }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      // 保单联动更新是同事务的：失败时原因要说清楚，输入保留可直接重试。
      formError.value = payload?.message || `理赔申请提交失败（${response.status}），数据未更新，请重试`
      return
    }
    showForm.value = false
    await reload()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '理赔申请请求未送达，可重试'
  } finally {
    submitting.value = false
  }
}

function resetFilters() {
  filters.value = { keyword: '', policy_no: '', insurer: '', status: '' }
  exportResult.value = null
  exportError.value = ''
  void reload()
}

function currentParams(): URLSearchParams {
  const params = new URLSearchParams()
  Object.entries(filters.value).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  return params
}

async function reload() {
  errorMessage.value = ''
  const params = currentParams()
  params.set('size', '200')
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) throw new Error('理赔列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await reloadSummary()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '理赔列表读取失败'
  }
}

async function reloadSummary() {
  // 合计单独走汇总接口，与导出共用同一套筛选，保证列表范围和包内合计对得上。
  try {
    const response = await request(`${ENDPOINT}/summary?${currentParams().toString()}`)
    if (response.ok) {
      const payload = await response.json()
      summaryAmount.value = Number(payload.total_amount ?? 0).toFixed(2)
    }
  } catch {
    // 汇总失败不阻塞列表，页脚保留上一次数字
  }
}

async function exportPackage() {
  exportError.value = ''
  exporting.value = true
  try {
    const response = await request(`${ENDPOINT}/export?${currentParams().toString()}`, { method: 'POST' })
    const payload = await response.json().catch(() => null)
    if (!response.ok) {
      exportResult.value = null
      exportError.value = `材料包导出失败（${response.status}）：${payload?.detail ?? '服务暂不可用'}，可点击重试`
      return
    }
    if (!payload?.ok) {
      // 例如“当前条件下没有命中记录”：保留筛选条件，用户改条件或直接重试。
      exportResult.value = null
      exportError.value = `${payload?.message ?? '材料包导出失败'}，可调整条件后重试`
      return
    }
    exportResult.value = payload as ExportResult
  } catch (error) {
    exportResult.value = null
    exportError.value = error instanceof Error ? `${error.message}，可点击重试` : '导出请求未送达，可重试'
  } finally {
    exporting.value = false
  }
}

function downloadPackage() {
  if (!exportResult.value) return
  const batch = encodeURIComponent(exportResult.value.batch_id)
  window.open(`${ENDPOINT}/export/${batch}/download`, '_blank')
}

onMounted(reload)
</script>
