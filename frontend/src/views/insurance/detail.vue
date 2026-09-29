<template>
  <section class="page" data-module="insurance-detail">
    <header class="page-head">
      <div>
        <h2>保单详情</h2>
        <p class="page-desc">查看保单信息与理赔申请记录，提交理赔申请后保单理赔次数与结案状态一并更新。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="goBack">返回列表</button>
      </div>
    </header>

    <div v-if="errorMessage" class="error-bar">
      <span class="error-text">{{ errorMessage }}</span>
      <button v-if="retryFn" class="btn" type="button" @click="retryFn">重试</button>
    </div>

    <div v-if="policy" class="detail-card">
      <h3>保单信息</h3>
      <div class="detail-grid">
        <div v-for="field in policyFields" :key="field" class="detail-item">
          <span class="detail-label">{{ field }}</span>
          <strong>{{ policy[field] ?? '—' }}</strong>
        </div>
      </div>
    </div>

    <section class="export-panel">
      <h3>理赔申请记录</h3>
      <form class="filter-bar" @submit.prevent="submitClaim">
        <label v-for="field in claimFields" :key="field.key" class="filter-item">
          <span>{{ field.label }}</span>
          <input v-model="claimForm[field.key]" :placeholder="field.placeholder" />
        </label>
        <button class="btn primary" type="submit">提交理赔申请</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in claimColumns" :key="column">{{ column }}</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="claim in claims" :key="String(claim.id)">
            <td v-for="column in claimColumns" :key="column">{{ claim[column] ?? '—' }}</td>
            <td class="row-actions">
              <button
                v-for="action in claimActions"
                :key="action"
                class="link"
                type="button"
                @click="runClaimAction(action, claim)"
              >
                {{ action }}
              </button>
            </td>
          </tr>
          <tr v-if="!claims.length">
            <td :colspan="claimColumns.length + 1" class="empty-state">暂无理赔申请记录</td>
          </tr>
        </tbody>
      </table>
    </section>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/insurance'
const route = useRoute()
const router = useRouter()
const policyId = String(route.params.id)

const policyFields = ["保单号", "承保单位", "保额", "险种", "保险期间", "理赔次数", "结案状态", "status"]
const claimColumns = ["理赔单号", "关联保单", "理赔金额", "申请日期", "理赔状态", "理赔说明"]
const claimActions = ["受理", "赔付", "结案", "驳回"]
const claimFields = [
  { key: '理赔单号', label: '理赔单号', placeholder: '如 CLM-0005' },
  { key: '理赔金额', label: '理赔金额（元）', placeholder: '如 10000' },
  { key: '申请日期', label: '申请日期', placeholder: '如 2026-09-29' },
  { key: '理赔说明', label: '理赔说明', placeholder: '如 事故损失' },
]

const policy = ref<Row | null>(null)
const claims = ref<Row[]>([])
const errorMessage = ref('')
const retryFn = ref<(() => void) | null>(null)
const claimForm = ref<Record<string, string>>({})

function setError(message: string, retry?: () => void) {
  errorMessage.value = message
  retryFn.value = retry ?? null
}

function clearError() {
  errorMessage.value = ''
  retryFn.value = null
}

function goBack() {
  router.push('/insurance')
}

async function loadPolicy() {
  clearError()
  try {
    const response = await request(`${ENDPOINT}/${policyId}`)
    if (!response.ok) {
      const payload = await response.json().catch(() => null)
      throw new Error(payload?.detail || '保单详情读取失败')
    }
    policy.value = await response.json()
  } catch (error) {
    setError(error instanceof Error ? error.message : '保单详情读取失败', () => void loadPolicy())
  }
}

async function loadClaims() {
  try {
    const response = await request(`${ENDPOINT}/${policyId}/claims`)
    if (!response.ok) return
    const payload = await response.json()
    claims.value = payload.items ?? []
  } catch {
    // 理赔记录加载失败不阻塞详情展示
  }
}

async function submitClaim() {
  clearError()
  try {
    const response = await request(`${ENDPOINT}/${policyId}/claims`, {
      method: 'POST',
      body: JSON.stringify({ values: claimForm.value }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      setError(payload?.message || '理赔申请提交失败，请稍后重试', () => void submitClaim())
      return
    }
    claimForm.value = {}
    await Promise.all([loadPolicy(), loadClaims()])
  } catch (error) {
    setError(error instanceof Error ? error.message : '理赔申请提交失败', () => void submitClaim())
  }
}

async function runClaimAction(action: string, claim: Row) {
  clearError()
  try {
    const response = await request(`${ENDPOINT}/claims/${claim.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      setError(payload?.message || '理赔动作未生效，请稍后重试', () => void runClaimAction(action, claim))
      return
    }
    await Promise.all([loadPolicy(), loadClaims()])
  } catch (error) {
    setError(error instanceof Error ? error.message : '理赔动作执行失败', () => void runClaimAction(action, claim))
  }
}

onMounted(() => {
  void loadPolicy()
  void loadClaims()
})
</script>
