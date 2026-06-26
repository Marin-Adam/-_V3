<template>
  <div class="alerts-page">
    <el-card shadow="never" class="alerts-card">
      <template #header><div class="header-row"><span>🚨 预警中心</span><el-select v-model="filterLevel" placeholder="级别筛选" clearable style="width:120px"><el-option label="P0 严重" value="P0" /><el-option label="P1 警告" value="P1" /><el-option label="P2 提示" value="P2" /></el-select></div></template>
      <el-table :data="items" style="width:100%" row-key="timestamp" v-loading="loading" empty-text="暂无预警">
        <el-table-column label="级别" width="80"><template #default="{row}"><el-tag :type="sevTag(row.severity)" size="small">{{ row.severity }}</el-tag></template></el-table-column>
        <el-table-column prop="type" label="类型" width="120" />
        <el-table-column prop="description" label="描述" min-width="300" />
        <el-table-column label="偏离" width="100"><template #default="{row}">{{ row.deviation_pct ? row.deviation_pct + '%' : '-' }}</template></el-table-column>
        <el-table-column prop="timestamp" label="时间" width="180"><template #default="{row}">{{ row.timestamp?.slice(11,19) }}</template></el-table-column>
        <el-table-column label="操作" width="100"><template #default="{row}"><el-button size="small" type="primary" @click="resolve(row)">处理</el-button></template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { alertsAPI } from '@/services/api'

const items = ref([])
const filterLevel = ref(null)
const loading = ref(false)
let timer = null

function sevTag(s) { return { P0: 'danger', P1: 'warning', P2: 'info' }[s] || 'info' }

async function fetch() {
  loading.value = true
  try {
    const { data } = await alertsAPI.list(1, filterLevel.value)
    items.value = data.items || []
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}

async function resolve(row) {
  try { await alertsAPI.resolve(row.timestamp); ElMessage.success('已处理'); fetch() }
  catch (e) { ElMessage.error('处理失败') }
}

watch(filterLevel, fetch)
onMounted(() => { fetch(); timer = setInterval(fetch, 10000) })
onUnmounted(() => { if (timer) { clearInterval(timer); timer = null } })
</script>

<style scoped>
.alerts-page { max-width: 1200px; margin: 0 auto; }
.alerts-card { background: #1a1a2e !important; border: 1px solid #2a2a3e !important; }
.alerts-card :deep(.el-card__header) { color: #e0e0e0; border-bottom: 1px solid #2a2a3e; }
.header-row { display: flex; justify-content: space-between; align-items: center; }
</style>
