import type { AgentReply, CategoryRule, Commitment, FinanceSummary, Goal, Insight, Transaction, WorkSession } from './types'

const DEFAULT_PRODUCTION_API_URL = 'https://finance-decision-os.onrender.com'
const API_BASE_URL = resolveApiBaseUrl()
const AUTH_STORAGE_KEY = 'finance-os-basic-auth'

function resolveApiBaseUrl() {
  const fromEnv = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')
  if (fromEnv) return fromEnv

  const hostname = window.location.hostname
  if (hostname !== 'localhost' && hostname !== '127.0.0.1') {
    return DEFAULT_PRODUCTION_API_URL
  }

  return ''
}

function apiUrl(path: string) {
  return `${API_BASE_URL}${path}`
}

function authHeaders(headers?: HeadersInit) {
  const nextHeaders = new Headers(headers)
  const token = localStorage.getItem(AUTH_STORAGE_KEY)
  if (token && !nextHeaders.has('Authorization')) {
    nextHeaders.set('Authorization', `Basic ${token}`)
  }
  return nextHeaders
}

function encodeBasicAuth(username: string, password: string) {
  return btoa(unescape(encodeURIComponent(`${username}:${password}`)))
}

function askCredentials() {
  const username = window.prompt('Usuario')
  if (!username) return null
  const password = window.prompt('Senha')
  if (!password) return null
  const token = encodeBasicAuth(username, password)
  localStorage.setItem(AUTH_STORAGE_KEY, token)
  return token
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const requestOptions: RequestInit = { ...options, headers: authHeaders(options?.headers) }
  let response = await fetch(apiUrl(path), requestOptions)
  if (response.status === 401) {
    localStorage.removeItem(AUTH_STORAGE_KEY)
    const token = askCredentials()
    if (token) {
      const headers = authHeaders(options?.headers)
      headers.set('Authorization', `Basic ${token}`)
      response = await fetch(apiUrl(path), { ...options, headers })
    }
  }
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || response.statusText)
  }
  return response.json() as Promise<T>
}

export function getSummary() {
  return request<FinanceSummary>('/api/dashboard')
}

export function getInsights() {
  return request<Insight[]>('/api/insights')
}

export function getTransactions(params: Record<string, string | number | undefined> = {}) {
  const search = new URLSearchParams()
  search.set('limit', String(params.limit ?? 80))
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && key !== 'limit') search.set(key, String(value))
  }
  return request<Transaction[]>(`/api/transactions?${search.toString()}`)
}

export function getWorkSessions(limit = 200) {
  return request<WorkSession[]>(`/api/work-sessions?limit=${limit}`)
}

export function getCommitments() {
  return request<Commitment[]>('/api/commitments')
}

export function createTransaction(payload: Omit<Transaction, 'id' | 'source'>) {
  return request<{ id: number; category: string; duplicated: boolean }>('/api/transactions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function updateTransactionCategory(
  id: number,
  payload: Pick<Transaction, 'category'> & Partial<Pick<Transaction, 'transaction_type' | 'is_internal'>>,
) {
  return request<{ id: number; category: string; transaction_type: string; is_internal: boolean }>(`/api/transactions/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function reprocessTransactions() {
  return request<{ ok: boolean; updated: number; preservedManual: boolean }>('/api/transactions/reprocess', {
    method: 'POST',
  })
}

export function askAgent(message: string) {
  return request<AgentReply>('/api/agent/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
}

export function importCsv(file: File) {
  const body = new FormData()
  body.append('file', file)
  return request<{ imported: number; duplicated: number; skipped: number }>('/api/import', {
    method: 'POST',
    body,
  })
}

export function getCategoryRules() {
  return request<CategoryRule[]>('/api/category-rules')
}

export function createCategoryRule(payload: {
  pattern: string
  category: string
  transaction_type: string
  is_internal: boolean
}) {
  return request<CategoryRule>('/api/category-rules', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function deleteCategoryRule(id: number) {
  return request<{ ok: boolean }>(`/api/category-rules/${id}`, {
    method: 'DELETE',
  })
}

export function getGoals() {
  return request<Goal[]>('/api/goals')
}

export function createGoal(payload: Omit<Goal, 'id'>) {
  return request<{ id: number; ok: boolean }>('/api/goals', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
