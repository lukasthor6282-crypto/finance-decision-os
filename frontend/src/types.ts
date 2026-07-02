export type Kpis = {
  balance: number
  income: number
  expenses: number
  grossExpenses: number
  refunds: number
  previousExpenses: number
  net: number
  savingsRate: number
  projectedExpense: number
  projectedBalance: number
  dailyBurn: number
  runwayDays: number | null
  cashRisk: string
  riskLevel: 'ok' | 'warn' | 'danger'
  healthScore: number
  healthLabel: string
}

export type Transaction = {
  id: number
  date: string
  description: string
  amount: number
  category: string
  account: string
  source: string
  notes?: string
  merchant?: string
  normalized_description?: string
  is_recurring?: number
  transaction_type?: string
  is_internal?: number | boolean
  duplicate_group?: string
  category_locked?: number | boolean
}

export type WorkSession = {
  id: number
  date: string
  start_time: string | null
  end_time: string | null
  break_minutes: number
  hourly_rate: number
  hours: number
  gross_amount: number
  description: string
  notes?: string | null
  transaction_id?: number | null
  created_at?: string
}

export type MonthlyPoint = {
  month: string
  income: number
  expenses: number
  net: number
}

export type CategoryPoint = {
  category: string
  value: number
  count: number
  share: number
}

export type BudgetStatus = {
  category: string
  spent: number
  limit: number
  remaining: number
  ratio: number
  projected: number
  projectedRatio: number
  status: 'ok' | 'warn' | 'danger'
}

export type ActionItem = {
  priority: string
  title: string
  detail: string
  impact?: string
}

export type Goal = {
  id: number
  name: string
  target_amount: number
  current_amount: number
  due_date: string
  priority: string
  progress?: number
  remaining?: number
  monthlyRequired?: number | null
}

export type Insight = {
  type: string
  severity: 'low' | 'medium' | 'high'
  title: string
  message: string
}

export type AlertItem = {
  type: string
  severity: 'low' | 'medium' | 'high'
  title: string
  message: string
  action?: string
  data?: unknown
}

export type CategoryRule = {
  id: number | null
  pattern: string
  category: string
  transaction_type: string
  is_internal: number | boolean
  priority: number
  created_at: string | null
  source: 'custom' | 'system'
  patterns: string[]
}

export type RecurringExpense = {
  merchant: string
  category: string
  averageAmount: number
  lastDate: string
  monthsDetected: number
  annualizedCost: number
}

export type FinanceSummary = {
  asOf: string
  month: string
  kpis: Kpis
  monthlySeries: MonthlyPoint[]
  categorySpend: CategoryPoint[]
  budgetStatus: BudgetStatus[]
  recurring: RecurringExpense[]
  anomalies: Array<{ message: string; amount: number; category: string; baseline?: number }>
  recentTransactions: Transaction[]
  actionPlan: ActionItem[]
  goals: Goal[]
  insights: Insight[]
  alerts: AlertItem[]
}

export type AgentReply = {
  answer: string
  actions: string[]
  confidence: number
  mode: string
  intent?: string
  data?: unknown
}
