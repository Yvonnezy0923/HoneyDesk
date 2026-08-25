import axios from 'axios';

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/',
  timeout: 120000,
});

export const api = {
  // chat
  sendMessage: (message: string, agent_code = 'ops_query', session_id = '') =>
    http.post('/api/chat/send', { message, agent_code, session_id }).then(r => r.data),
  messages: (params?: { session_id?: string; agent_code?: string; limit?: number }) =>
    http.get('/api/chat/messages', { params }).then(r => r.data),
  injectArtifact: (payload: Record<string, unknown>) =>
    http.post('/api/chat/inject-artifact', payload).then(r => r.data),

  // sessions
  sessions: (agent_code?: string) =>
    http.get('/api/chat/sessions', { params: { agent_code } }).then(r => r.data),
  createSession: (agent_code: string, title = '新会话') =>
    http.post('/api/chat/sessions', { agent_code, title }).then(r => r.data),
  renameSession: (id: string, title: string) =>
    http.post(`/api/chat/sessions/${id}/rename`, { title }).then(r => r.data),
  deleteSession: (id: string) => http.delete(`/api/chat/sessions/${id}`).then(r => r.data),

  // approvals
  approvals: (status?: string, agent_code?: string) =>
    http.get('/api/approvals', { params: { status, agent_code } }).then(r => r.data),
  pendingCount: () => http.get('/api/approvals/pending-count').then(r => r.data),
  decide: (id: string, payload: Record<string, unknown>) =>
    http.post(`/api/approvals/${id}/decide`, payload).then(r => r.data),

  // artifacts
  artifacts: (params?: Record<string, unknown>) =>
    http.get('/api/artifacts', { params }).then(r => r.data),
  deleteArtifact: (id: string) => http.delete(`/api/artifacts/${id}`).then(r => r.data),
  setTtl: (id: string, days: number, is_temp = true) =>
    http.post(`/api/artifacts/${id}/ttl`, { days, is_temp }).then(r => r.data),

  // dashboard
  overview: () => http.get('/api/dashboard/overview').then(r => r.data),
  opByAction: () => http.get('/api/dashboard/op-by-action').then(r => r.data),
  trend: (days = 14, scope = 'all') =>
    http.get('/api/dashboard/trend', { params: { days, scope } }).then(r => r.data),

  // boss global view (P1)
  bossView: () => http.get('/api/boss/view').then(r => r.data),
  alerts: (params?: Record<string, unknown>) =>
    http.get('/api/alerts', { params }).then(r => r.data),
  updateAlertStatus: (id: string, status: string, resolution = '') =>
    http.post(`/api/alerts/${id}/status`, { status, resolution }).then(r => r.data),
  linkageEvents: (limit = 100) =>
    http.get('/api/linkage/events', { params: { limit } }).then(r => r.data),
  linkageChains: (limit = 50) =>
    http.get('/api/linkage/chains', { params: { limit } }).then(r => r.data),
  linkageStats: () => http.get('/api/linkage/stats').then(r => r.data),

  // audit
  logs: (params?: Record<string, unknown>) =>
    http.get('/api/audit/logs', { params }).then(r => r.data),
  approvalRecords: () => http.get('/api/audit/approval-records').then(r => r.data),

  // knowledge
  documents: () => http.get('/api/knowledge').then(r => r.data),
  kbStats: () => http.get('/api/knowledge/stats').then(r => r.data),
  kbSync: () => http.get('/api/knowledge/sync').then(r => r.data),
  ingestDoc: (payload: Record<string, unknown>) =>
    http.post('/api/knowledge/ingest', payload).then(r => r.data),
  ingestTable: (table: string) =>
    http.post(`/api/knowledge/ingest-table/${table}`).then(r => r.data),
  deleteDoc: (id: string) => http.delete(`/api/knowledge/${id}`).then(r => r.data),

  // tools
  tools: () => http.get('/api/tools').then(r => r.data),
  updateTool: (code: string, payload: Record<string, unknown>) =>
    http.put(`/api/tools/${code}`, payload).then(r => r.data),

  // tasks
  tasks: (page = 1, pageSize = 20, filters: Record<string, unknown> = {}) =>
    http.get('/api/tasks', { params: { page, page_size: pageSize, ...filters } }).then(r => r.data),
  task: (id: string) => http.get(`/api/tasks/${id}`).then(r => r.data),

  // settings
  settings: () => http.get('/api/settings').then(r => r.data),
  saveLLM: (payload: Record<string, unknown>) =>
    http.post('/api/settings/llm', payload).then(r => r.data),
  testLLM: () => http.post('/api/settings/llm/test').then(r => r.data),

  // import
  importRows: (payload: Record<string, unknown>) =>
    http.post('/api/import/rows', payload).then(r => r.data),

  // monitor alerts
  monitorRules: () => http.get('/api/monitor/rules').then(r => r.data),
  monitorFields: () => http.get('/api/monitor/fields').then(r => r.data),
  monitorCreateRule: (payload: Record<string, unknown>) =>
    http.post('/api/monitor/rules', payload).then(r => r.data),
  monitorUpdateRule: (id: string, payload: Record<string, unknown>) =>
    http.put(`/api/monitor/rules/${id}`, payload).then(r => r.data),
  monitorDeleteRule: (id: string) =>
    http.delete(`/api/monitor/rules/${id}`).then(r => r.data),
  monitorEvaluateAll: () =>
    http.post('/api/monitor/rules/evaluate-all').then(r => r.data),
  monitorEvaluateRule: (id: string) =>
    http.post(`/api/monitor/rules/${id}/evaluate`).then(r => r.data),
  monitorRuleData: (id: string, days = 30) =>
    http.get(`/api/monitor/rules/${id}/data`, { params: { days } }).then(r => r.data),
  monitorHistory: (ruleId?: string) =>
    http.get('/api/monitor/history', { params: { rule_id: ruleId } }).then(r => r.data),
  monitorFrequency: () =>
    http.get('/api/monitor/frequency').then(r => r.data),
  monitorSetFrequency: (frequency: string) =>
    http.post('/api/monitor/frequency', { frequency }).then(r => r.data),

  // combo strategy (P2 cross-scenario)
  comboTemplates: () =>
    http.get('/api/combo/templates').then(r => r.data),
  comboExecute: (payload: Record<string, unknown>) =>
    http.post('/api/combo/execute', payload).then(r => r.data),
  comboStrategies: (limit = 50) =>
    http.get('/api/combo/strategies', { params: { limit } }).then(r => r.data),
  // tools rebuild (P2 auto-extension)
  toolsRebuild: () =>
    http.post('/api/tools/rebuild').then(r => r.data),

  // memory governance (P2 PII治理)
  memoryGovernance: () =>
    http.get('/api/memories/governance').then(r => r.data),
  updateMemoryGovernance: (payload: Record<string, unknown>) =>
    http.put('/api/memories/governance', payload).then(r => r.data),
  memoryPiiReport: () =>
    http.get('/api/memories/pii-report').then(r => r.data),
  memoryAutoExpire: () =>
    http.post('/api/memories/auto-expire').then(r => r.data),

  // compliance (P2 合规审计视图)
  complianceOverview: () =>
    http.get('/api/compliance/overview').then(r => r.data),
  complianceExport: () =>
    http.get('/api/compliance/export', { responseType: 'blob' }).then(r => r.data),
  complianceChecklist: () =>
    http.get('/api/compliance/checklist').then(r => r.data),
};