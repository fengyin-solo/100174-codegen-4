<template>
  <section class="page">
    <header class="detail-head">
      <RouterLink class="back-link" to="/insurance">← 返回保单列表</RouterLink>
      <h2 style="margin: 0; font-size: 18px">保单详情</h2>
    </header>

    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

    <template v-if="entry">
      <div class="detail-grid">
        <div v-for="field in detailFields" :key="field" class="detail-item">
          <span class="k">{{ field }}</span>
          <span>{{ entry[field] ?? '—' }}</span>
        </div>
        <div class="detail-item">
          <span class="k">保单状态</span>
          <span>{{ entry.status ?? '—' }}</span>
        </div>
      </div>

      <div class="detail-section">
        <h3>保单材料（{{ materials.length }} 份，历史材料长期保留，仅追加）</h3>
        <ul class="material-list">
          <li v-for="(item, index) in materials" :key="index">
            <span>📎 {{ item.name }} <em class="material-meta">［{{ item.category }}］</em></span>
            <span class="material-meta">{{ item.uploaded_at }}</span>
          </li>
          <li v-if="!materials.length" class="empty-state">暂无材料</li>
        </ul>

        <form class="inline-form" @submit.prevent="uploadMaterial">
          <label>
            材料文件
            <input ref="fileInput" type="file" @change="onFilePicked" />
          </label>
          <label>
            材料类别
            <input v-model="materialCategory" placeholder="如 保单正本 / 理赔材料" />
          </label>
          <button class="btn primary" type="submit" :disabled="uploading">
            {{ uploading ? '上传中…' : '追加材料' }}
          </button>
        </form>
        <p v-if="materialMessage" :class="materialOk ? 'success-text' : 'error-text'" style="margin: 8px 0 0; font-size: 12px">
          {{ materialMessage }}
        </p>
      </div>

      <div class="detail-section">
        <h3>本保单项下理赔记录（{{ relatedClaims.length }} 笔）</h3>
        <table class="data-table">
          <thead>
            <tr><th>理赔单号</th><th>出险日期</th><th>申请金额</th><th>状态</th><th>申请时间</th><th>结案时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="claim in relatedClaims" :key="String(claim.id)">
              <td>
                <RouterLink class="link" :to="`/claim/${claim.id}`">{{ claim['理赔单号'] }}</RouterLink>
              </td>
              <td>{{ claim['出险日期'] }}</td>
              <td>{{ claim['申请金额'] }}</td>
              <td>
                <span :class="claim.closed ? 'badge badge-closed' : 'badge badge-open'">
                  {{ claim.closed ? '已结案' : '理赔中' }}
                </span>
              </td>
              <td>{{ claim['申请时间'] }}</td>
              <td>{{ claim['结案时间'] || '—' }}</td>
            </tr>
            <tr v-if="!relatedClaims.length">
              <td colspan="6" class="empty-state">暂无理赔申请</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type Material = { name: string; category: string; uploaded_at: string; encoding?: string }

const route = useRoute()
const entryId = String(route.params.id)

const entry = ref<Row | null>(null)
const relatedClaims = ref<Row[]>([])
const errorMessage = ref('')

const detailFields = ['保单号', '承保单位', '投保设备', '保额', '保费', '保险期限起', '保险期限止', '经办人', '登记日期', '理赔次数', '结案状态']
const materials = computed<Material[]>(() => (entry.value?.['保单材料'] as Material[] | undefined) ?? [])

const fileInput = ref<HTMLInputElement | null>(null)
const pickedFile = ref<File | null>(null)
const materialCategory = ref('')
const uploading = ref(false)
const materialMessage = ref('')
const materialOk = ref(false)

function onFilePicked(event: Event) {
  const target = event.target as HTMLInputElement
  pickedFile.value = target.files?.[0] ?? null
}

async function uploadMaterial() {
  materialMessage.value = ''
  if (!pickedFile.value) {
    materialOk.value = false
    materialMessage.value = '请先选择要上传的材料文件'
    return
  }
  uploading.value = true
  try {
    const params = new URLSearchParams({ filename: pickedFile.value.name })
    if (materialCategory.value.trim()) params.set('category', materialCategory.value.trim())
    const response = await request(`/api/insurance/${entryId}/materials?${params.toString()}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: pickedFile.value,
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      materialOk.value = false
      materialMessage.value = payload?.message || '材料归档失败，请重试'
      return
    }
    materialOk.value = true
    materialMessage.value = payload.message
    pickedFile.value = null
    materialCategory.value = ''
    if (fileInput.value) fileInput.value.value = ''
    await loadDetail()
  } catch (error) {
    materialOk.value = false
    materialMessage.value = error instanceof Error ? error.message : '材料上传请求失败，可重试'
  } finally {
    uploading.value = false
  }
}

async function loadDetail() {
  errorMessage.value = ''
  try {
    const detailResp = await request(`/api/insurance/${entryId}`)
    if (!detailResp.ok) throw new Error(`保单详情读取失败（${detailResp.status}）`)
    entry.value = await detailResp.json()

    const claimsResp = await request(
      `/api/claim?policy_no=${encodeURIComponent(policyNoForQuery())}&size=200`,
    )
    if (claimsResp.ok) {
      const payload = await claimsResp.json()
      relatedClaims.value = payload.items ?? []
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保单详情读取失败，可重试'
  }
}

function policyNoForQuery(): string {
  return entry.value ? String(entry.value['保单号'] ?? '') : ''
}

onMounted(loadDetail)
</script>
