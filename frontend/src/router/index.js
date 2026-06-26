import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', name: 'Dashboard', component: () => import('@/pages/Dashboard/index.vue') },
  { path: '/agent', name: 'AgentChat', component: () => import('@/pages/AgentChat/index.vue') },
  { path: '/alerts', name: 'Alerts', component: () => import('@/pages/Alerts/index.vue') },
  { path: '/insights', name: 'Insights', component: () => import('@/pages/Insights/index.vue') },
  { path: '/settings', name: 'Settings', component: () => import('@/pages/Settings/index.vue') },
]

export default createRouter({ history: createWebHistory(), routes })
