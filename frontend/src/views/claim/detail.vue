<template>
  <section class="page">
    <header class="detail-head">
      <RouterLink class="back-link" to="/claim">← 返回理赔列表</RouterLink>
      <h2 style="margin: 0; font-size: 18px">理赔申请详情</h2>
    </header>

    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

    <template v-if="entry">
      <div class="detail-grid">
        <div v-for="field in detailFields" :key="field" class="detail-item">
          <span class="k">{{ field }}</span>
          <span>{{ entry[field] ?? '—' }}</span>
        </div>
        <div class="detail-item">
          <span class="k">理赔状态</span>
          <span :class="entry.closed ? 'badge badge-closed' : 'badge badge-open'">
            {{ entry.closed ? '已结案' : '理赔中' }}
          </span>
        </div>
      </div>

      <div class="detail-section">
        <h3>事故经过</h3>
        <p style="margin: 0; font-size: 13px; white-space: pre-wrap;">{{ entry['事故经过'] }}</p>
      </div>

      <div class="detail-section">
        <h3>关联保单（理赔次数、结案状态由系统联动回算）</h3>
        <div v-if="policy" class="detail-grid" style="border: none; padding: 0">
          <div v-for="field in policyFields" :key="field" class="detail-item">
            <span class="k">{{ field }}</span>
            <span>{{ policy[field] ?? '—' }}</span>
          </div>
        </div>
        <p v-else class="material-meta">未找到关联保单</p>
        <p style="margin: 8px 0 0">
          <RouterLink class="link" :to="`/insurance/${policyId}`">前往保单详情与材料 →</RouterLink>
        </p>
      </div>

      <div class="detail-section">
        <h3>结案处理</h3>
        <template v-if="entry.closed">
          <p class="material-meta" style="margin: 0">该理赔单已结案，不能重复结案。</p>
        </template>
        <template v-else>
          <form class="inline-form" @submit.prevent="closeClaim">
            <label style="flex: 1">
              结案结论
              <input v-model="conclusion" placeholder="如 赔付 10800 元，理赔结案" style="min-width: 320px" />
            </label>
            <button class="btn primary" type="submit" :disabled="closing">
              {{ closing ? '提交中…' : '确认结案' }}
            </button>
          </form>
        </template>
        <p v-if="actionMessage" :class="actionOk ? 'success-text' : 'error-text'" style="margin: 8px 0 0; font-size: 12px">
          {{ actionMessage }}
        </p>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

const route = useRoute()
const entryId = String(route.params.id)

const entry = ref<Row | null>(null)
const policy = ref<Row | null>(null)
const policyId = ref('')
const errorMessage = ref('')

const detailFields = ['理赔单号', '保单号', '承保单位', '事故设备', '出险日期', '申请金额', '申请人', '申请时间', '结案时间', '结案结论']
const policyFields = ['保单号', '承保单位', '投保设备', '保额', '理赔次数', '结案状态']

const conclusion = ref('')
const closing = ref(false)
const actionMessage = ref('')
const actionOk = ref(false)

async function closeClaim() {
  actionMessage.value = ''
  closing.value = true
  try {
    const response = await request(`/api/claim/${entryId}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action: '确认结案', 结案结论: conclusion.value } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      actionOk.value = false
      actionMessage.value = payload?.message || `结案失败（${response.status}），数据未更新，可重试`
      return
    }
    actionOk.value = true
    actionMessage.value = `${payload.message}。返回列表即可看到最新次数与在途数。`
    conclusion.value = ''
    await loadDetail()
  } catch (error) {
    actionOk.value = false
    actionMessage.value = error instanceof Error ? error.message : '结案请求未送达，可重试'
  } finally {
    closing.value = false
  }
}

async function loadDetail() {
  errorMessage.value = ''
  try {
    const resp = await request(`/api/claim/${entryId}`)
    if (!resp.ok) throw new Error(`理赔详情读取失败（${resp.status}）`)
    const loaded = (await resp.json()) as Row
    entry.value = loaded

    const policyNo = String(loaded['保单号'] ?? '')
    if (policyNo) {
      const policyResp = await request(`/api/insurance?keyword=${encodeURIComponent(policyNo)}&size=1`)
      if (policyResp.ok) {
        const payload = await policyResp.json()
        const matched = (payload.items ?? []).find((item: Row) => item['保单号'] === policyNo)
        policy.value = matched ?? null
        policyId.value = matched?.id != null ? String(matched.id) : ''
      }
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '理赔详情读取失败，可重试'
  }
}

onMounted(loadDetail)
</script>
