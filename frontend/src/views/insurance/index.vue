<template>
  <section class="page" data-module="insurance">
    <header class="page-head">
      <div>
        <h2>保险与理赔管理</h2>
        <p class="page-desc">登记保单号、承保单位、保额与理赔申请，支持把理赔申请连同保单材料打包导出成一份文件供线下提交。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="toggleCreate">登记保单</button>
        <button class="btn" type="button" :disabled="exporting" @click="exportPackage">
          {{ exporting ? '打包中…' : '打包导出理赔材料' }}
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="showCreate" class="filter-bar" @submit.prevent="submitCreate">
      <label v-for="field in createFields" :key="field.key" class="filter-item">
        <span>{{ field.label }}</span>
        <input v-model="createForm[field.key]" :placeholder="field.placeholder" />
      </label>
      <button class="btn primary" type="submit">提交登记</button>
      <button class="btn ghost" type="button" @click="toggleCreate">取消</button>
    </form>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>关键字</span>
        <input v-model="filters.keyword" placeholder="按保单号或承保单位检索" />
      </label>
      <label class="filter-item">
        <span>保单状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="item in policyStatuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="errorMessage" class="error-bar">
      <span class="error-text">{{ errorMessage }}</span>
      <button v-if="retryFn" class="btn" type="button" @click="retryFn">重试</button>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <RouterLink class="link" :to="`/insurance/${row.id}`">查看详情</RouterLink>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无保单数据，可先登记保单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条保单记录；保额合计 {{ totals.coverage }} 元，理赔合计 {{ totals.claim }} 元</span>
      <span v-if="lastExport" class="muted">最近打包：{{ lastExport.batch_no }}（{{ lastExport.exported_at }}）</span>
    </footer>

    <section class="export-panel">
      <h3>打包导出记录</h3>
      <p class="page-desc">按当前筛选条件打包，同一批条件重复导出会覆盖旧包而不是追加；文件里的条数与合计和列表当前范围一致。</p>
      <div v-if="lastExport" class="export-current">
        <span>
          本次打包：<strong>{{ lastExport.file_name }}</strong>
          （{{ lastExport.summary.policy_count }} 张保单 / {{ lastExport.summary.claim_count }} 条理赔，
          保额 {{ lastExport.summary.total_coverage }} 元，理赔 {{ lastExport.summary.total_claim_amount }} 元）
        </span>
        <a class="link" :href="`${ENDPOINT}/packages/${lastExport.batch_no}/download`" target="_blank">下载文件</a>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>批次号</th>
            <th>文件名</th>
            <th>保单数</th>
            <th>理赔数</th>
            <th>保额合计</th>
            <th>理赔合计</th>
            <th>导出时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="pkg in packages" :key="pkg.batch_no">
            <td>{{ pkg.batch_no }}</td>
            <td>{{ pkg.file_name }}</td>
            <td>{{ pkg.summary.policy_count }}</td>
            <td>{{ pkg.summary.claim_count }}</td>
            <td>{{ pkg.summary.total_coverage }}</td>
            <td>{{ pkg.summary.total_claim_amount }}</td>
            <td>{{ pkg.exported_at }}</td>
            <td><a class="link" :href="`${ENDPOINT}/packages/${pkg.batch_no}/download`" target="_blank">下载</a></td>
          </tr>
          <tr v-if="!packages.length">
            <td colspan="8" class="empty-state">暂无打包记录，可点击「打包导出理赔材料」生成</td>
          </tr>
        </tbody>
      </table>
    </section>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type PackageInfo = {
  batch_no: string
  file_name: string
  exported_at: string
  summary: {
    policy_count: number
    claim_count: number
    total_coverage: number
    total_claim_amount: number
    in_transit_count: number
  }
}

const ENDPOINT = '/api/insurance'
const columns = ["保单号", "承保单位", "保额", "险种", "理赔次数", "结案状态", "status"]
const policyStatuses = ["保障中", "已失效"]
const createFields = [
  { key: '保单号', label: '保单号', placeholder: '如 INS-0004' },
  { key: '承保单位', label: '承保单位', placeholder: '如 中国人民财产保险' },
  { key: '保额', label: '保额（元）', placeholder: '如 500000' },
  { key: '险种', label: '险种', placeholder: '如 财产一切险' },
  { key: '保险期间', label: '保险期间', placeholder: '如 2026-01-01 至 2026-12-31' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const retryFn = ref<(() => void) | null>(null)
const filters = ref<Record<string, string>>({ keyword: '', status: '' })
const showCreate = ref(false)
const createForm = ref<Record<string, string>>({})
const exporting = ref(false)
const packages = ref<PackageInfo[]>([])
const lastExport = ref<PackageInfo | null>(null)
const totals = ref({ coverage: 0, claim: 0 })
const stats = ref([
  { label: '在途理赔数', value: 0 },
  { label: '保单总数', value: 0 },
  { label: '保额合计', value: 0 },
  { label: '理赔合计', value: 0 },
])

function setError(message: string, retry?: () => void) {
  errorMessage.value = message
  retryFn.value = retry ?? null
}

function clearError() {
  errorMessage.value = ''
  retryFn.value = null
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function toggleCreate() {
  showCreate.value = !showCreate.value
  if (showCreate.value) createForm.value = {}
}

async function submitCreate() {
  clearError()
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      setError(payload?.message || '保单登记失败，请稍后重试', () => void submitCreate())
      return
    }
    showCreate.value = false
    await reload()
  } catch (error) {
    setError(error instanceof Error ? error.message : '保单登记失败', () => void submitCreate())
  }
}

async function exportPackage() {
  clearError()
  exporting.value = true
  try {
    const query = new URLSearchParams(filters.value).toString()
    const response = await request(`${ENDPOINT}/export?${query}`, { method: 'POST' })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      setError(payload?.message || '打包导出失败，请稍后重试', () => void exportPackage())
      return
    }
    lastExport.value = { ...payload.entry, summary: payload.entry.summary }
    await loadPackages()
  } catch (error) {
    setError(error instanceof Error ? error.message : '打包导出失败', () => void exportPackage())
  } finally {
    exporting.value = false
  }
}

async function loadPackages() {
  try {
    const response = await request(`${ENDPOINT}/packages`)
    if (!response.ok) return
    const payload = await response.json()
    packages.value = payload.items ?? []
  } catch {
    // 打包记录加载失败不阻塞列表展示
  }
}

async function reload() {
  clearError()
  const query = new URLSearchParams(filters.value).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('保单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    const summary = payload.summary ?? {}
    totals.value = {
      coverage: summary.total_coverage ?? 0,
      claim: summary.total_claim_amount ?? 0,
    }
    stats.value = [
      { label: '在途理赔数', value: summary.in_transit_count ?? 0 },
      { label: '保单总数', value: summary.policy_count ?? total.value },
      { label: '保额合计', value: summary.total_coverage ?? 0 },
      { label: '理赔合计', value: summary.total_claim_amount ?? 0 },
    ]
  } catch (error) {
    setError(error instanceof Error ? error.message : '保单列表读取失败', () => void reload())
  }
}

onMounted(() => {
  void reload()
  void loadPackages()
})
</script>
