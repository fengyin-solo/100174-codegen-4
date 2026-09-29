<template>
  <section class="page" data-module="insurance">
    <header class="page-head">
      <div>
        <h2>保险保单管理</h2>
        <p class="page-desc">登记保单号、承保单位与保额；理赔次数与结案状态由理赔申请联动回算，列表实时反映最新值。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记保单</button>
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
        <span>保单号 / 投保设备</span>
        <input v-model="filters.keyword" placeholder="按保单号或投保设备检索" />
      </label>
      <label class="filter-item">
        <span>承保单位</span>
        <input v-model="filters.insurer" placeholder="按承保单位检索" />
      </label>
      <label class="filter-item">
        <span>保单状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

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
            <RouterLink class="link" :to="`/insurance/${row.id}`">查看详情/材料</RouterLink>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无保单数据，可先登记保单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 张保单</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="showForm" class="modal-mask" @click.self="showForm = false">
      <div class="modal">
        <div class="modal-head">
          <h3>登记保单</h3>
          <button class="modal-close" type="button" @click="showForm = false">×</button>
        </div>
        <form class="form-grid" @submit.prevent="submitCreate">
          <label><span class="req">保单号</span><input v-model="form.保单号" placeholder="如 INSR-2026-0004" /></label>
          <label><span class="req">承保单位</span><input v-model="form.承保单位" placeholder="保险公司全称" /></label>
          <label class="span-2"><span class="req">投保设备</span><input v-model="form.投保设备" placeholder="如 锅炉设备 BOIL-0001" /></label>
          <label><span class="req">保额（元）</span><input v-model="form.保额" type="number" min="0" step="0.01" /></label>
          <label>保费（元）<input v-model="form.保费" type="number" min="0" step="0.01" /></label>
          <label>保险期限起<input v-model="form.保险期限起" type="date" /></label>
          <label>保险期限止<input v-model="form.保险期限止" type="date" /></label>
          <label class="span-2">经办人<input v-model="form.经办人" /></label>
        </form>
        <p v-if="formError" class="error-text">{{ formError }}</p>
        <div class="modal-foot">
          <button class="btn" type="button" @click="showForm = false">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitCreate">
            {{ submitting ? '提交中…' : '提交登记' }}
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

const ENDPOINT = '/api/insurance'
const columns = ['保单号', '承保单位', '投保设备', '保额', '保费', '保险期限起', '保险期限止', '经办人', '登记日期', '理赔次数', '结案状态']
const statuses = ['保障中', '已到期']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({ keyword: '', insurer: '', status: '' })

const stats = computed(() => {
  // 统计口径取当前筛选范围（最多 200 条），和列表看到的范围一致。
  const list = rows.value
  const amount = list.reduce((sum, row) => sum + Number(row['保额'] || 0), 0)
  const ongoing = list.filter((row) => row['结案状态'] === '有在途理赔').length
  return [
    { label: '当前范围保单', value: total.value },
    { label: '保额合计（元）', value: amount.toLocaleString() },
    { label: '在途理赔保单', value: ongoing },
  ]
})

const showForm = ref(false)
const submitting = ref(false)
const formError = ref('')
const emptyForm = () => ({
  保单号: '', 承保单位: '', 投保设备: '', 保额: '', 保费: '',
  保险期限起: '', 保险期限止: '', 经办人: '',
})
const form = ref(emptyForm())

function openCreate() {
  form.value = emptyForm()
  formError.value = ''
  showForm.value = true
}

async function submitCreate() {
  formError.value = ''
  submitting.value = true
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: form.value }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      // 接口失败说明原因，弹窗保留输入，允许修正后重试。
      formError.value = payload?.message || `保单登记失败（${response.status}），请重试`
      return
    }
    showForm.value = false
    await reload()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '保单登记请求失败，可重试'
  } finally {
    submitting.value = false
  }
}

function resetFilters() {
  filters.value = { keyword: '', insurer: '', status: '' }
  void reload()
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  Object.entries(filters.value).forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  params.set('size', '200')
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) throw new Error('保单列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保单列表读取失败'
  }
}

onMounted(reload)
</script>
