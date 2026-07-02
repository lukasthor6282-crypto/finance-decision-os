import type { AgentReply, FinanceSummary, Goal, Insight, Transaction } from './types'

const API_BASE_URL = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')
const AUTH_STORAGE_KEY = 'finance-os-basic-auth'

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

export function createTransaction(payload: Omit<Transaction, 'id' | 'source'>) {
  return request<{ id: number; category: string; duplicated: boolean }>('/api/transactions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
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
