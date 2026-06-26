<template>
  <div id="app-container">
    <el-container>
      <el-aside width="200px" class="app-sidebar">
        <div class="logo">
          <h2>📊 AI 电商看板</h2>
          <p class="subtitle">Agent Skills + MCP</p>
        </div>
        <el-menu :default-active="activeMenu" router background-color="#1a1a2e" text-color="#a0a0b0" active-text-color="#4fc3f7">
          <el-menu-item index="/dashboard"><el-icon><DataBoard /></el-icon><span>实时监控大屏</span></el-menu-item>
          <el-menu-item index="/agent"><el-icon><ChatDotRound /></el-icon><span>AI 智能分析</span></el-menu-item>
          <el-menu-item index="/insights"><el-icon><TrendCharts /></el-icon><span>营销洞察</span></el-menu-item>
          <el-menu-item index="/alerts"><el-icon><Bell /></el-icon><span>预警中心</span></el-menu-item>
          <el-menu-item index="/settings"><el-icon><Setting /></el-icon><span>Skills 配置</span></el-menu-item>
        </el-menu>
      </el-aside>
      <el-container>
        <el-header class="app-header">
          <span class="header-title">{{ pageTitle }}</span>
          <el-tag type="info">v0.1.0</el-tag>
        </el-header>
        <el-main class="app-main"><router-view /></el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { DataBoard, ChatDotRound, TrendCharts, Bell, Setting } from '@element-plus/icons-vue'

const route = useRoute()
const activeMenu = computed(() => route.path)
const pageTitle = computed(() => {
  const titles = { '/dashboard': '实时监控大屏', '/agent': 'AI 智能分析', '/insights': '营销洞察', '/alerts': '预警中心', '/settings': 'Skills 配置' }
  return titles[route.path] || '电商智能决策平台'
})
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f0f1a; color: #e0e0e0; }
#app-container { height: 100vh; }
.app-sidebar { background: #1a1a2e; border-right: 1px solid #2a2a3e; }
.logo { padding: 20px; text-align: center; border-bottom: 1px solid #2a2a3e; }
.logo h2 { color: #4fc3f7; font-size: 16px; }
.logo .subtitle { color: #6a6a8a; font-size: 11px; margin-top: 4px; }
.el-menu { border-right: none !important; }
.app-header { background: #1a1a2e; border-bottom: 1px solid #2a2a3e; display: flex; align-items: center; justify-content: space-between; padding: 0 24px; height: 56px; }
.header-title { font-size: 16px; font-weight: 600; color: #e0e0e0; }
.app-main { background: #0f0f1a; padding: 24px; min-height: calc(100vh - 56px); }
</style>
