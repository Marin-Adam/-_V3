import axios from 'axios'

const API_BASE = '/api/v1'
const api = axios.create({ baseURL: API_BASE, timeout: 60000, headers: { 'Content-Type': 'application/json' } })

api.interceptors.response.use(r => r, e => {
  console.error('[API Error]', e.response?.data?.detail || e.message)
  return Promise.reject(e)
})

export const dashboardAPI = {
  overview: () => api.get('/dashboard/overview'),
  metrics: (timeRange = '1h') => api.get('/dashboard/metrics', { params: { time_range: timeRange } }),
  anomalies: () => api.get('/dashboard/anomalies'),
  topProducts: () => api.get('/dashboard/top-products'),
}

export const agentAPI = {
  chat: (query) => api.post('/agent/chat', { query }),
  chatStream: (query) => {
    const params = new URLSearchParams({ query })
    return new EventSource(`${API_BASE}/agent/chat/stream?${params}`)
  },
  skills: () => api.get('/agent/skills'),
  analyze: (task) => api.post('/agent/analyze', { task }),
}

export const alertsAPI = {
  list: (page = 1, level = null) => {
    const params = { page, page_size: 20 }
    if (level) params.level = level
    return api.get('/alerts', { params })
  },
  resolve: (id) => api.put(`/alerts/${id}`, { status: 'resolved' }),
  createRule: (rule) => api.post('/alerts/rules', rule),
}

export const adminAPI = {
  stats: () => api.get('/admin/stats'),
  reloadSkills: () => api.post('/admin/skills/reload'),
}

export const insightsAPI = {
  overview: (params = {}) => api.get('/insights/overview', { params }),
  categories: (params = {}) => api.get('/insights/categories', { params }),
  ageGroups: (params = {}) => api.get('/insights/age-groups', { params }),
  regions: (params = {}) => api.get('/insights/regions', { params }),
  repurchase: () => api.get('/insights/repurchase'),
  sentiment: () => api.get('/insights/sentiment'),
}

export default api
