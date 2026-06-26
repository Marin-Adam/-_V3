<template>
  <div class="dashboard">
    <!-- Metric Cards -->
    <el-row :gutter="16" class="metric-row">
      <el-col :span="6"><MetricCard title="今日 GMV" :value="'¥' + fmt(overview.gmv)" trend="up" :sub="overview.order_count + ' 笔订单'" color="#4fc3f7" /></el-col>
      <el-col :span="6"><MetricCard title="订单量" :value="overview.order_count" trend="up" :sub="'转化率 ' + overview.conversion_rate + '%'" color="#66bb6a" /></el-col>
      <el-col :span="6"><MetricCard title="访客 UV" :value="overview.total_uv" trend="down" :sub="'PV ' + overview.total_pv" color="#ffa726" /></el-col>
      <el-col :span="6"><MetricCard title="加购数" :value="overview.add_cart_count" :sub="overview.anomaly_active ? '⚠️ 异常活跃' : '✅ 正常'" :color="overview.anomaly_active ? '#ef5350' : '#42a5f5'" /></el-col>
    </el-row>

    <!-- Charts -->
    <el-row :gutter="16" class="chart-row">
      <el-col :span="16">
        <el-card class="chart-card" shadow="never">
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>📈 GMV 趋势</span>
              <div style="display:flex;align-items:center;gap:12px">
                <span style="color:#6a6a8a;font-size:12px">刷新: {{ lastRefresh }}</span>
                <el-button size="small" type="primary" @click="manualRefresh" :loading="refreshing">
                  🔄 刷新数据
                </el-button>
              </div>
            </div>
          </template>
          <v-chart :option="gmvChartOption" style="height:360px" autoresize />
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card class="chart-card" shadow="never">
          <template #header><span>📊 渠道占比</span></template>
          <v-chart :option="channelChartOption" style="height:360px" autoresize />
        </el-card>
      </el-col>
    </el-row>

    <!-- Bottom row: Anomalies + Top Products -->
    <el-row :gutter="16" class="bottom-row">
      <el-col :span="12">
        <el-card class="chart-card" shadow="never">
          <template #header><span>🚨 实时预警</span></template>
          <div v-if="anomalies.length === 0" class="empty">暂无预警</div>
          <div v-for="a in anomalies" :key="a.timestamp" class="anomaly-item" :class="a.severity">
            <el-tag :type="severityTag(a.severity)" size="small">{{ a.severity }}</el-tag>
            <span>{{ a.description }}</span>
          </div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card class="chart-card" shadow="never">
          <template #header><span>🔥 热销商品</span></template>
          <div v-for="(p, i) in topProducts" :key="p.product_id" class="product-item">
            <span class="rank">{{ i + 1 }}</span>
            <span class="name">{{ p.product_name }}</span>
            <span class="gmv">¥{{ fmt(p.gmv) }}</span>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, TitleComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import MetricCard from '@/components/MetricCard.vue'
import { dashboardAPI } from '@/services/api'

use([LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent, CanvasRenderer])

const overview = reactive({ gmv: 0, order_count: 0, total_uv: 0, total_pv: 0, conversion_rate: 0, add_cart_count: 0, anomaly_active: false, channel_breakdown: {} })
const metrics = ref([])
const anomalies = ref([])
const topProducts = ref([])
const lastRefresh = ref('--')
const refreshing = ref(false)
let timer = null

const gmvChartOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 50, right: 20, top: 20, bottom: 30 },
  xAxis: { type: 'category', data: metrics.value.map(m => m.time?.slice(11, 16) || ''), axisLabel: { color: '#888', rotate: metrics.value.length > 20 ? 45 : 0 } },
  yAxis: { type: 'value', axisLabel: { color: '#888', formatter: v => '¥' + (v/1000).toFixed(0) + 'k' } },
  series: [
    { name: 'GMV', type: 'line', data: metrics.value.map(m => m.gmv), smooth: true, lineStyle: { color: '#4fc3f7', width: 2 }, itemStyle: { color: '#4fc3f7' }, areaStyle: { color: 'rgba(79,195,247,0.1)' } },
    { name: '订单数', type: 'line', data: metrics.value.map(m => m.orders), smooth: true, lineStyle: { color: '#66bb6a', width: 2 }, itemStyle: { color: '#66bb6a' } },
  ],
}))

const channelChartOption = computed(() => {
  const data = Object.entries(overview.channel_breakdown || {}).map(([name, value]) => ({ name, value }))
  return { tooltip: { trigger: 'item' }, series: [{ type: 'pie', radius: ['45%', '75%'], center: ['50%', '50%'], data, label: { color: '#aaa' }, itemStyle: { borderRadius: 4 } }] }
})

function fmt(n) { return (n || 0).toLocaleString() }
function severityTag(s) { return { P0: 'danger', P1: 'warning', P2: 'info' }[s] || 'info' }

async function refresh() {
  try {
    const [ov, mt, an, tp] = await Promise.all([dashboardAPI.overview(), dashboardAPI.metrics('1h'), dashboardAPI.anomalies(), dashboardAPI.topProducts()])
    Object.assign(overview, ov.data)
    metrics.value = [...(mt.data.data || [])]
    anomalies.value = [...(an.data.anomalies || [])]
    topProducts.value = [...(tp.data.products || [])]
    const now = new Date()
    lastRefresh.value = now.getHours().toString().padStart(2,'0') + ':' + now.getMinutes().toString().padStart(2,'0') + ':' + now.getSeconds().toString().padStart(2,'0')
  } catch (e) { console.error('Dashboard refresh failed', e) }
}

async function manualRefresh() {
  refreshing.value = true
  await refresh()
  setTimeout(() => { refreshing.value = false }, 500)
}

onMounted(() => { refresh(); timer = setInterval(refresh, 5000) })
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.dashboard { max-width: 1400px; margin: 0 auto; }
.metric-row { margin-bottom: 16px; }
.chart-row { margin-bottom: 16px; }
.bottom-row { margin-bottom: 16px; }
.chart-card { background: #1a1a2e !important; border: 1px solid #2a2a3e !important; }
.chart-card :deep(.el-card__header) { color: #e0e0e0; border-bottom: 1px solid #2a2a3e; }
.empty { color: #6a6a8a; text-align: center; padding: 24px; }
.anomaly-item { display: flex; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid #2a2a3e; font-size: 13px; }
.anomaly-item:last-child { border-bottom: none; }
.product-item { display: flex; align-items: center; padding: 8px 0; border-bottom: 1px solid #2a2a3e; }
.product-item:last-child { border-bottom: none; }
.rank { width: 24px; color: #ffa726; font-weight: 700; }
.name { flex: 1; color: #e0e0e0; }
.gmv { color: #4fc3f7; font-weight: 600; }
</style>
