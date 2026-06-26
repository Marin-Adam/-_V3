<template>
  <div class="insights-page">
    <div class="page-header">
      <h2>📊 营销洞察</h2>
      <el-tag type="success" size="large">V3.0 多智能体驱动</el-tag>
      <span class="hint">以销量为最高级枢轴，联动下钻分析</span>
    </div>

    <!-- Module ①: Category Ranking -->
    <el-row :gutter="16" class="module-row">
      <el-col :span="12">
        <el-card shadow="hover" class="insight-card">
          <template #header>
            <div class="card-header">
              <span>① 品类销量排行 Top 10</span>
              <el-select v-model="selectedCategory" placeholder="全部品类" size="small" clearable style="width:140px" @change="refreshAll">
                <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
              </el-select>
            </div>
          </template>
          <div class="chart-container" ref="categoryChartRef"></div>
        </el-card>
      </el-col>

      <!-- Module ②: Age Distribution -->
      <el-col :span="12">
        <el-card shadow="hover" class="insight-card">
          <template #header>
            <div class="card-header">
              <span>② 年龄分段购买力</span>
            </div>
          </template>
          <div class="chart-container" ref="ageChartRef"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Module ③: Regional Heatmap -->
    <el-row :gutter="16" class="module-row">
      <el-col :span="24">
        <el-card shadow="hover" class="insight-card">
          <template #header>
            <div class="card-header">
              <span>③ 地区销售排行</span>
            </div>
          </template>
          <div class="chart-container region-chart" ref="regionChartRef"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Module ④ & ⑤ -->
    <el-row :gutter="16" class="module-row">
      <el-col :span="12">
        <el-card shadow="hover" class="insight-card">
          <template #header>
            <div class="card-header">
              <span>④ 复购率分析</span>
            </div>
          </template>
          <div class="repurchase-section">
            <div class="big-number">
              <span class="number">{{ repurchaseData.rate }}%</span>
              <span class="label">总复购率</span>
            </div>
            <el-divider />
            <div class="repurchase-detail">
              <div class="detail-item">
                <span class="detail-value">{{ repurchaseData.totalUsers }}</span>
                <span class="detail-label">总用户数</span>
              </div>
              <div class="detail-item">
                <span class="detail-value">{{ repurchaseData.repurchaseUsers }}</span>
                <span class="detail-label">复购用户</span>
              </div>
              <div class="detail-item">
                <span class="detail-value">{{ repurchaseData.totalOrders }}</span>
                <span class="detail-label">总订单数</span>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- Module ⑤: Sentiment -->
      <el-col :span="12">
        <el-card shadow="hover" class="insight-card">
          <template #header>
            <div class="card-header">
              <span>⑤ 好评/差评分布</span>
            </div>
          </template>
          <div class="chart-container" ref="sentimentChartRef"></div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Agent Status Bar -->
    <el-card shadow="hover" class="agent-status-card">
      <template #header>
        <span>🤖 A2A 多智能体状态</span>
      </template>
      <div class="agent-status-row">
        <el-tag v-for="agent in agentStatus" :key="agent.name"
          :type="agent.online ? 'success' : 'danger'"
          :effect="agent.online ? 'dark' : 'plain'"
          style="margin-right: 12px">
          {{ agent.name }} :{{ agent.port }} {{ agent.online ? '✅' : '❌' }}
        </el-tag>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import * as echarts from 'echarts'
import { insightsAPI } from '@/services/api'

// Chart refs
const categoryChartRef = ref(null)
const ageChartRef = ref(null)
const regionChartRef = ref(null)
const sentimentChartRef = ref(null)

// Chart instances
let categoryChart = null
let ageChart = null
let regionChart = null
let sentimentChart = null

// Data
const categories = ref(['数码电子', '电脑外设', '运动户外', '家用电器'])
const selectedCategory = ref('')
const selectedProduct = ref('')

const repurchaseData = ref({ rate: 0, totalUsers: 0, repurchaseUsers: 0, totalOrders: 0 })

const agentStatus = ref([
  { name: 'DataAgent', port: 8010, online: false },
  { name: 'AnalyzeAgent', port: 8011, online: false },
  { name: 'SentimentAgent', port: 8012, online: false },
  { name: 'ReportAgent', port: 8013, online: false },
])

// ── Lifecycle ───────────────────────────────────────────────────
onMounted(async () => {
  await nextTick()
  initCharts()
  await refreshAll()
  checkAgentStatus()
  // Auto-refresh every 10 seconds
  window._insightsTimer = setInterval(refreshAll, 10000)
})

onUnmounted(() => {
  if (window._insightsTimer) clearInterval(window._insightsTimer)
  categoryChart?.dispose()
  ageChart?.dispose()
  regionChart?.dispose()
  sentimentChart?.dispose()
})

// ── Init Charts ─────────────────────────────────────────────────
function initCharts() {
  if (categoryChartRef.value) categoryChart = echarts.init(categoryChartRef.value)
  if (ageChartRef.value) ageChart = echarts.init(ageChartRef.value)
  if (regionChartRef.value) regionChart = echarts.init(regionChartRef.value)
  if (sentimentChartRef.value) sentimentChart = echarts.init(sentimentChartRef.value)

  window.addEventListener('resize', () => {
    categoryChart?.resize()
    ageChart?.resize()
    regionChart?.resize()
    sentimentChart?.resize()
  })
}

// ── Data Refresh ────────────────────────────────────────────────
async function refreshAll() {
  try {
    const params = {}
    if (selectedCategory.value) params.category = selectedCategory.value
    if (selectedProduct.value) params.product_id = selectedProduct.value

    const overview = await insightsAPI.overview(params)
    const sentiment = await insightsAPI.sentiment()
    const repurchase = await insightsAPI.repurchase()

    updateCategoryChart(overview)
    updateAgeChart(overview)
    updateRegionChart(overview)
    updateSentimentChart(sentiment)
    updateRepurchase(repurchase)
  } catch (e) {
    console.error('Insights refresh failed:', e)
  }
}

// ── Chart Updates ───────────────────────────────────────────────
function updateCategoryChart(data) {
  if (!categoryChart) return
  let cats = data.top_categories || []
  // Fallback: use channels if top_categories is empty (DataGenerator uses channels as categories)
  if (cats.length === 0 && data.channel_pcts) {
    cats = Object.entries(data.channel_pcts).map(([name, gmv]) => ({ name, gmv }))
  }
  // Still empty? Show loading state
  if (cats.length === 0) {
    cats = [{ name: '等待数据...', gmv: 0 }]
  }
  categoryChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '10%', bottom: '3%', containLabel: true },
    xAxis: { type: 'value', axisLabel: { formatter: '¥{value}' } },
    yAxis: { type: 'category', data: cats.map(c => c.name).reverse(), axisLabel: { fontSize: 11 } },
    series: [{
      type: 'bar',
      data: cats.map(c => c.gmv).reverse(),
      itemStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
          { offset: 0, color: '#4fc3f7' }, { offset: 1, color: '#0277bd' }
        ]),
        borderRadius: [0, 4, 4, 0],
      },
      label: { show: true, position: 'right', formatter: '¥{c}', fontSize: 10 },
    }]
  })
}

function updateAgeChart(data) {
  if (!ageChart) return
  const ages = data.age_distribution || {}
  const ageData = [
    { name: '18-24岁', value: ages['18-24'] || 0 },
    { name: '25-30岁', value: ages['25-30'] || 0 },
    { name: '31-40岁', value: ages['31-40'] || 0 },
    { name: '40岁以上', value: ages['40+'] || 0 },
  ]
  // If no real data, show simulated
  if (ageData.every(d => d.value === 0)) {
    ageData[0].value = Math.random() * 5000 + 3000
    ageData[1].value = Math.random() * 8000 + 5000
    ageData[2].value = Math.random() * 4000 + 2000
    ageData[3].value = Math.random() * 2000 + 500
  }
  ageChart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: ¥{c} ({d}%)' },
    legend: { orient: 'vertical', right: 10, top: 'center', textStyle: { color: '#a0a0b0', fontSize: 11 } },
    series: [{
      type: 'pie',
      radius: ['45%', '75%'],
      center: ['40%', '50%'],
      data: ageData,
      label: { formatter: '{b}\n{d}%', fontSize: 10 },
      itemStyle: { borderRadius: 6, borderColor: '#0f0f1a', borderWidth: 3 },
      colors: ['#4fc3f7', '#81c784', '#ffb74d', '#e57373'],
    }]
  })
}

function updateRegionChart(data) {
  if (!regionChart) return
  const regions = data.region_distribution || {}
  const regionNames = Object.keys(regions)
  // If no real data, show simulated
  const allRegions = regionNames.length > 0
    ? regionNames
    : ['华东', '华南', '华北', '西南', '华中']
  const values = regionNames.length > 0
    ? allRegions.map(r => regions[r] || 0)
    : allRegions.map(() => Math.random() * 10000 + 2000)

  regionChart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: allRegions, axisLabel: { color: '#a0a0b0' } },
    yAxis: { type: 'value', axisLabel: { formatter: '¥{value}', color: '#a0a0b0' } },
    series: [{
      type: 'bar',
      data: values.map((v, i) => ({
        value: v,
        itemStyle: {
          color: ['#4fc3f7', '#81c784', '#ffb74d', '#e57373', '#ba68c8'][i],
          borderRadius: [6, 6, 0, 0],
        }
      })),
      barWidth: '50%',
      label: { show: true, position: 'top', formatter: '¥{c}', color: '#a0a0b0', fontSize: 10 },
    }]
  })
}

function updateSentimentChart(data) {
  if (!sentimentChart) return
  const dist = data.distribution || { positive: 0, negative: 0, neutral: 0 }
  sentimentChart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c}%' },
    legend: { bottom: 0, textStyle: { color: '#a0a0b0', fontSize: 11 } },
    series: [{
      type: 'pie',
      radius: ['50%', '70%'],
      center: ['50%', '45%'],
      data: [
        { name: '好评 😊', value: dist.positive || 45, itemStyle: { color: '#81c784' } },
        { name: '中性 😐', value: dist.neutral || 35, itemStyle: { color: '#ffb74d' } },
        { name: '差评 😟', value: dist.negative || 20, itemStyle: { color: '#e57373' } },
      ],
      label: { formatter: '{b}\n{d}%', fontSize: 11 },
      emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.5)' } },
    }]
  })
}

function updateRepurchase(data) {
  repurchaseData.value = {
    rate: data.repurchase_rate || 0,
    totalUsers: data.total_users || 0,
    repurchaseUsers: data.repurchase_users || 0,
    totalOrders: data.total_orders || 0,
  }
}

async function checkAgentStatus() {
  try {
    const resp = await fetch('/api/v1/agent/agents/status')
    const data = await resp.json()
    if (data.agents) {
      const nameMap = { data: 'DataAgent', analyze: 'AnalyzeAgent', sentiment: 'SentimentAgent', report: 'ReportAgent' }
      for (const agent of agentStatus.value) {
        const key = Object.keys(nameMap).find(k => nameMap[k] === agent.name)
        agent.online = key ? data.agents[key]?.online : false
      }
    }
  } catch {
    // Fallback: try direct (will work now with CORS)
    for (const agent of agentStatus.value) {
      try {
        const resp = await fetch(`http://localhost:${agent.port}/health`)
        agent.online = resp.ok
      } catch { agent.online = false }
    }
  }
}
</script>

<style scoped>
.insights-page { padding: 8px 0; }
.page-header { display: flex; align-items: center; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }
.page-header h2 { color: #e0e0e0; font-size: 20px; margin: 0; }
.page-header .hint { color: #6a6a8a; font-size: 12px; margin-left: 8px; }

.module-row { margin-bottom: 16px; }

.insight-card {
  background: #1a1a2e;
  border: 1px solid #2a2a3e;
  color: #e0e0e0;
}
.insight-card :deep(.el-card__header) {
  background: #16213e;
  border-bottom: 1px solid #2a2a3e;
  padding: 12px 16px;
}
.card-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.card-header span { font-weight: 600; font-size: 14px; color: #4fc3f7; }

.chart-container { width: 100%; height: 280px; }
.region-chart { height: 300px; }

/* Repurchase */
.repurchase-section { text-align: center; padding: 16px 0; }
.big-number { margin-bottom: 12px; }
.big-number .number { font-size: 48px; font-weight: 700; color: #4fc3f7; }
.big-number .label { display: block; color: #6a6a8a; font-size: 13px; margin-top: 4px; }
.repurchase-detail { display: flex; justify-content: space-around; margin-top: 12px; }
.detail-item { text-align: center; }
.detail-value { display: block; font-size: 24px; font-weight: 600; color: #e0e0e0; }
.detail-label { display: block; font-size: 11px; color: #6a6a8a; margin-top: 4px; }

/* Agent Status */
.agent-status-card {
  background: #1a1a2e;
  border: 1px solid #2a2a3e;
  color: #e0e0e0;
  margin-top: 16px;
}
.agent-status-card :deep(.el-card__header) {
  background: #16213e;
  border-bottom: 1px solid #2a2a3e;
  padding: 10px 16px;
  color: #4fc3f7;
  font-weight: 600;
}
.agent-status-row { display: flex; flex-wrap: wrap; gap: 8px; padding: 8px 0; }
</style>
