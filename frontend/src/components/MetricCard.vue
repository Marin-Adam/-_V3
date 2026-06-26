<template>
  <el-card class="metric-card" shadow="never">
    <div class="mc-title">{{ title }}</div>
    <div class="mc-value" :style="{color}">{{ value }}</div>
    <div class="mc-sub">
      <span v-if="trend === 'up'">🟢 ↑ </span>
      <span v-else-if="trend === 'down'">🔴 ↓ </span>
      {{ sub }}
    </div>
  </el-card>
</template>

<script setup>
defineProps({ title: String, value: [String,Number], trend: String, sub: String, color: { type: String, default: '#4fc3f7' } })
</script>

<style scoped>
.metric-card { background: #1a1a2e !important; border: 1px solid #2a2a3e !important; }
.mc-title { font-size: 13px; color: #6a6a8a; margin-bottom: 8px; }
.mc-value { font-size: 28px; font-weight: 700; margin-bottom: 6px; }
.mc-sub { font-size: 12px; color: #888; }
</style>
