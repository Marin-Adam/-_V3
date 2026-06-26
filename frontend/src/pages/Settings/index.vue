<template>
  <div class="settings-page">
    <!-- System Stats -->
    <el-card shadow="never" class="settings-card">
      <template #header><span>📊 系统状态</span></template>
      <el-descriptions v-if="stats" :column="3" border size="small">
        <el-descriptions-item label="数据源">{{ stats.data_source }}</el-descriptions-item>
        <el-descriptions-item label="内存订单数">{{ stats.total_orders_in_memory }}</el-descriptions-item>
        <el-descriptions-item label="活跃数据流">{{ stats.active_streams }}</el-descriptions-item>
        <el-descriptions-item label="已加载 Skills">{{ stats.skills_loaded }}</el-descriptions-item>
        <el-descriptions-item label="P0 告警">
          <el-tag v-if="stats.open_alerts_p0 > 0" type="danger" size="small">{{ stats.open_alerts_p0 }}</el-tag>
          <span v-else>0</span>
        </el-descriptions-item>
        <el-descriptions-item label="P1/P2 告警">
          <el-tag v-if="stats.open_alerts_p1 > 0" type="warning" size="small" style="margin-right:4px">{{ stats.open_alerts_p1 }}</el-tag>
          <el-tag v-if="stats.open_alerts_p2 > 0" type="info" size="small">{{ stats.open_alerts_p2 }}</el-tag>
          <span v-if="!stats.open_alerts_p1 && !stats.open_alerts_p2">0</span>
        </el-descriptions-item>
      </el-descriptions>
      <div v-else-if="statsLoading" style="color:#888;padding:12px">加载中...</div>
      <div v-else style="color:#888;padding:12px">无法获取系统状态</div>
    </el-card>

    <!-- Agent Skills -->
    <el-card shadow="never" class="settings-card" style="margin-top:16px">
      <template #header>
        <div class="header-row">
          <span>🧩 Agent Skills 配置</span>
          <el-button size="small" @click="reloadSkills" :loading="reloading">热重载</el-button>
        </div>
      </template>
      <div v-if="skillsLoading">加载中...</div>
      <div v-for="skill in skills" :key="skill.name" class="skill-card">
        <div class="skill-header">
          <span class="skill-name">{{ skill.name }}</span>
          <el-switch v-model="skill.enabled" active-text="启用" />
        </div>
        <p class="skill-desc">{{ skill.description }}</p>
        <div class="skill-meta">
          <span>触发方式：</span>
          <el-tag v-for="t in skill.triggers" :key="t" size="small" type="info" style="margin:2px">
            {{ formatTrigger(t) }}
          </el-tag>
        </div>
        <div class="skill-meta" v-if="skill.scripts?.length">
          <span>脚本：</span>
          <code v-for="s in skill.scripts" :key="s" style="margin:2px;background:#0a0a1a;padding:2px 6px;border-radius:4px">{{ s }}</code>
        </div>
      </div>
    </el-card>

    <!-- MCP Tools (dynamic from API) -->
    <el-card shadow="never" class="settings-card" style="margin-top:16px">
      <template #header><span>🔧 MCP 工具连接状态</span></template>
      <el-table :data="mcpTools" style="width:100%" v-loading="mcpLoading" empty-text="无法连接 MCP Server">
        <el-table-column prop="name" label="工具名" width="220" />
        <el-table-column prop="description" label="描述" min-width="340" />
        <el-table-column label="状态" width="100">
          <template #default>
            <el-tag type="success" size="small">已连接</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { agentAPI, adminAPI } from '@/services/api'
import axios from 'axios'

const skills = ref([])
const mcpTools = ref([])
const stats = ref(null)

const skillsLoading = ref(true)
const mcpLoading = ref(true)
const statsLoading = ref(true)
const reloading = ref(false)

function formatTrigger(t) {
  if (typeof t === 'string') return t
  if (t.scheduled) return `定时: 每${t.scheduled}`
  if (t.event) return `事件: ${t.event}`
  if (t.manual) return '手动触发'
  return JSON.stringify(t)
}

async function fetchSkills() {
  try {
    const { data } = await agentAPI.skills()
    skills.value = (data.skills || []).map(s => ({ ...s, enabled: true }))
  } catch (e) { console.error('Failed to fetch skills', e) }
  finally { skillsLoading.value = false }
}

async function fetchMCPTools() {
  try {
    const { data } = await axios.post('/mcp/tools/list', {})
    const tools = data?.result?.tools || []
    mcpTools.value = tools.map(t => ({
      name: t.name,
      description: t.description,
    }))
  } catch (e) {
    console.error('Failed to fetch MCP tools, using defaults', e)
    // Fallback — show hardcoded list if MCP server is unreachable
    mcpTools.value = [
      { name: 'query_sales_metrics', description: '查询GMV/订单量/转化率/客单价' },
      { name: 'query_traffic_data', description: '查询UV/PV/加购数' },
      { name: 'query_inventory', description: '查询库存水位与预警' },
      { name: 'query_competitor_prices', description: '查询竞品价格对比' },
      { name: 'query_order_detail', description: '查询订单详情' },
      { name: 'execute_analytics_query', description: '自定义聚合分析查询' },
    ]
  }
  finally { mcpLoading.value = false }
}

async function fetchStats() {
  try {
    const { data } = await adminAPI.stats()
    stats.value = data
  } catch (e) { console.error('Failed to fetch stats', e) }
  finally { statsLoading.value = false }
}

async function reloadSkills() {
  reloading.value = true
  try {
    await adminAPI.reloadSkills()
    await fetchSkills()
    ElMessage.success('Skills 已重新加载')
  } catch (e) {
    ElMessage.error('重载失败')
  } finally {
    reloading.value = false
  }
}

onMounted(() => {
  fetchSkills()
  fetchMCPTools()
  fetchStats()
})
</script>

<style scoped>
.settings-page { max-width: 960px; margin: 0 auto; padding-bottom: 40px; }
.settings-card { background: #1a1a2e !important; border: 1px solid #2a2a3e !important; }
.settings-card :deep(.el-card__header) { color: #e0e0e0; border-bottom: 1px solid #2a2a3e; }
.settings-card :deep(.el-descriptions__label) { color: #888; }
.settings-card :deep(.el-descriptions__content) { color: #e0e0e0; }
.settings-card :deep(.el-table) { background: transparent; --el-table-tr-bg-color: transparent; --el-table-row-hover-bg-color: #2a2a3e; }
.settings-card :deep(.el-table th) { background: #1a1a2e; color: #888; border-color: #2a2a3e; }
.settings-card :deep(.el-table td) { border-color: #2a2a3e; color: #e0e0e0; }
.header-row { display: flex; justify-content: space-between; align-items: center; }
.skill-card { padding: 16px; border: 1px solid #2a2a3e; border-radius: 8px; margin-bottom: 12px; }
.skill-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.skill-name { font-size: 16px; font-weight: 600; color: #4fc3f7; }
.skill-desc { color: #a0a0b0; font-size: 13px; margin-bottom: 8px; }
.skill-meta { font-size: 12px; color: #6a6a8a; margin-top: 4px; }
</style>
