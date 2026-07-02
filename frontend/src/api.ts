import type { AgentReply, FinanceSummary, Goal, Insight, Transaction } from './types'

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options)
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
