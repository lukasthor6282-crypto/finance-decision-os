import type { FormEvent } from 'react'
import type { CategoryRule, Commitment, FinanceSummary, Transaction, WorkSession } from './types'
import {
  Bell,
  Bot,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  Database,
  Home,
  MessageCircle,
  PieChart,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Send,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  Tags,
  TrendingDown,
  TrendingUp,
  Trash2,
  Upload,
  WalletCards,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  askAgent,
  createCategoryRule,
  deleteCategoryRule,
  getCategoryRules,
  getCommitments,
  getSummary,
  getTransactions,
  getWorkSessions,
  importCsv,
  reprocessTransactions,
  updateTransactionCategory,
} from './api'
import './App.css'

type ChatMessage = {
  author: 'Finance OS' | 'Voce'
  text: string
}

const navItems = [
  { label: 'Hoje', icon: <Home size={19} /> },
  { label: 'Receitas', icon: <CircleDollarSign size={19} /> },
  { label: 'Fluxo', icon: <TrendingUp size={19} /> },
  { label: 'Categorias', icon: <PieChart size={19} /> },
  { label: 'Horas', icon: <Clock3 size={19} /> },
  { label: 'Regras', icon: <Tags size={19} /> },
  { label: 'Dados', icon: <Database size={19} /> },
]

const fallbackMessages: ChatMessage[] = [
  {
    author: 'Finance OS',
    text: 'Carregando seus dados financeiros...',
  },
]

const money = (value = 0) =>
  new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value)

const todayIso = () => {
  const date = new Date()
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset())
  return date.toISOString().slice(0, 10)
}

const formatDate = (value: string) =>
  new Intl.DateTimeFormat('pt-BR', { weekday: 'short', day: '2-digit', month: '2-digit' }).format(new Date(`${value}T12:00:00`))

const BASE_CATEGORIES = [
  'Alimentacao',
  'Supermercado',
  'Transporte',
  'Moradia',
  'Assinaturas',
  'Saude',
  'Educacao',
  'Receita',
  'Transferencia',
  'Cartao',
  'Estorno',
  'Investimentos',
  'Outros',
]

const TRANSACTION_TYPES = [
  { value: 'expense', label: 'Despesa' },
  { value: 'income', label: 'Receita' },
  { value: 'transfer', label: 'Transferencia' },
  { value: 'card_payment', label: 'Fatura/cartao' },
  { value: 'refund', label: 'Estorno' },
  { value: 'investment', label: 'Investimento' },
]

const INTERNAL_TYPES = new Set(['transfer', 'card_payment', 'investment'])

function App() {
  const [summary, setSummary] = useState<FinanceSummary | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>(fallbackMessages)
  const [question, setQuestion] = useState('')
  const [activeNav, setActiveNav] = useState('Hoje')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [workSessions, setWorkSessions] = useState<WorkSession[]>([])
  const [commitments, setCommitments] = useState<Commitment[]>([])
  const [categoryRules, setCategoryRules] = useState<CategoryRule[]>([])
  const [rulesLoading, setRulesLoading] = useState(false)
  const [workLoading, setWorkLoading] = useState(false)
  const [moneyLoading, setMoneyLoading] = useState(false)
  const [notice, setNotice] = useState('')
  const [ruleForm, setRuleForm] = useState({
    pattern: '',
    category: 'Alimentacao',
    transaction_type: 'expense',
    is_internal: false,
  })
  const [workForm, setWorkForm] = useState({
    date: todayIso(),
    start: '',
    end: '',
    hourlyRate: '',
  })
  const fileInputRef = useRef<HTMLInputElement>(null)

  const loadDashboard = async () => {
    setLoading(true)
    setError('')
    try {
      const nextSummary = await getSummary()
      setSummary(nextSummary)
      setMessages((current) => {
        if (current !== fallbackMessages && current.length > 1) return current
        return [
          {
            author: 'Finance OS',
            text: `Dados carregados. Saldo ${money(nextSummary.kpis.balance)}. Proxima decisao: ${nextSummary.actionPlan[0]?.title ?? 'manter plano atual'}.`,
          },
        ]
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao carregar backend')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadDashboard()
  }, [])

  const loadRulesData = async () => {
    setRulesLoading(true)
    setError('')
    try {
      const [nextTransactions, nextRules] = await Promise.all([
        getTransactions({ limit: 80 }),
        getCategoryRules(),
      ])
      setTransactions(nextTransactions)
      setCategoryRules(nextRules)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao carregar regras')
    } finally {
      setRulesLoading(false)
    }
  }

  const loadWorkData = async () => {
    setWorkLoading(true)
    setError('')
    try {
      const sessions = await getWorkSessions(300)
      setWorkSessions(sessions)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao carregar banco de horas')
    } finally {
      setWorkLoading(false)
    }
  }

  const loadMoneyData = async () => {
    setMoneyLoading(true)
    setError('')
    try {
      const [nextTransactions, nextCommitments] = await Promise.all([
        getTransactions({ limit: 120 }),
        getCommitments(),
      ])
      setTransactions(nextTransactions)
      setCommitments(nextCommitments)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao carregar receitas e despesas')
    } finally {
      setMoneyLoading(false)
    }
  }

  useEffect(() => {
    if (activeNav === 'Regras') void loadRulesData()
    if (activeNav === 'Horas') void loadWorkData()
    if (activeNav === 'Receitas') void loadMoneyData()
  }, [activeNav])

  const decisions = useMemo(() => {
    return (summary?.actionPlan ?? []).slice(0, 3).map((item) => ({
      title: item.title,
      detail: item.detail,
      state: item.priority,
    }))
  }, [summary])

  const cards = useMemo(
    () => [
      {
        label: 'Saldo atual',
        value: money(summary?.kpis.balance),
        hint: loading ? 'sincronizando' : 'dados do backend',
        icon: <CircleDollarSign />,
      },
      {
        label: 'Queima diaria',
        value: money(summary?.kpis.dailyBurn),
        hint: 'media projetada',
        icon: <TrendingDown />,
      },
      {
        label: 'Reserva',
        value: `${summary?.kpis.savingsRate ?? 0}%`,
        hint: summary?.kpis.healthLabel ?? 'aguardando dados',
        icon: <CheckCircle2 />,
      },
    ],
    [loading, summary],
  )

  const riskRows = useMemo(() => {
    const budgets = summary?.budgetStatus ?? []
    if (!budgets.length) {
      return [
        { name: 'Hoje', value: summary?.kpis.cashRisk ?? 'carregando', width: '34%' },
        { name: '30 dias', value: summary?.kpis.riskLevel ?? 'ok', width: '52%' },
        { name: 'Score', value: `${summary?.kpis.healthScore ?? 0}/100`, width: '62%' },
      ]
    }
    return budgets.slice(0, 3).map((budget) => ({
      name: budget.category,
      value: `${budget.projectedRatio}%`,
      width: `${Math.min(Math.max(budget.projectedRatio, 8), 100)}%`,
    }))
  }, [summary])

  const categoryOptions = useMemo(() => {
    const values = new Set(BASE_CATEGORIES)
    summary?.categorySpend.forEach((item) => values.add(item.category))
    transactions.forEach((item) => values.add(item.category))
    categoryRules.forEach((item) => values.add(item.category))
    return Array.from(values).sort((a, b) => a.localeCompare(b))
  }, [categoryRules, summary, transactions])

  const workDays = useMemo(() => {
    const grouped = new Map<string, { date: string; hours: number; gross: number; count: number; sessions: WorkSession[] }>()
    workSessions.forEach((session) => {
      const row = grouped.get(session.date) ?? { date: session.date, hours: 0, gross: 0, count: 0, sessions: [] }
      row.hours += Number(session.hours) || 0
      row.gross += Number(session.gross_amount) || 0
      row.count += 1
      row.sessions.push(session)
      grouped.set(session.date, row)
    })
    return Array.from(grouped.values())
      .map((row) => ({
        ...row,
        hours: Number(row.hours.toFixed(4)),
        gross: Number(row.gross.toFixed(2)),
      }))
      .sort((a, b) => b.date.localeCompare(a.date))
  }, [workSessions])

  const workTotals = useMemo(() => {
    const hours = workSessions.reduce((sum, session) => sum + (Number(session.hours) || 0), 0)
    const gross = workSessions.reduce((sum, session) => sum + (Number(session.gross_amount) || 0), 0)
    return {
      hours: Number(hours.toFixed(2)),
      gross: Number(gross.toFixed(2)),
      days: workDays.length,
      averageRate: hours ? Number((gross / hours).toFixed(2)) : 0,
    }
  }, [workDays.length, workSessions])

  const moneyTotals = useMemo(() => {
    const income = transactions.filter((tx) => Number(tx.amount) > 0).reduce((sum, tx) => sum + Number(tx.amount), 0)
    const expenses = transactions.filter((tx) => Number(tx.amount) < 0).reduce((sum, tx) => sum + Math.abs(Number(tx.amount)), 0)
    const fixedExpenses = commitments
      .filter((item) => item.kind === 'expense' && Boolean(item.active))
      .reduce((sum, item) => sum + Number(item.amount), 0)
    const fixedIncome = commitments
      .filter((item) => item.kind === 'income' && Boolean(item.active))
      .reduce((sum, item) => sum + Number(item.amount), 0)
    const futureDebt = commitments
      .filter((item) => item.kind === 'expense' && item.installments_remaining)
      .reduce((sum, item) => sum + Number(item.amount) * Number(item.installments_remaining), 0)
    return {
      income: Number(income.toFixed(2)),
      expenses: Number(expenses.toFixed(2)),
      fixedExpenses: Number(fixedExpenses.toFixed(2)),
      fixedIncome: Number(fixedIncome.toFixed(2)),
      futureDebt: Number(futureDebt.toFixed(2)),
    }
  }, [commitments, transactions])

  const todayLabel = new Intl.DateTimeFormat('pt-BR', {
    weekday: 'long',
    day: '2-digit',
    month: 'short',
  }).format(new Date())

  const handleAsk = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const text = question.trim()
    if (!text || busy) return
    setQuestion('')
    setBusy(true)
    setMessages((current) => [...current, { author: 'Voce', text }])
    try {
      const reply = await askAgent(text)
      setMessages((current) => [...current, { author: 'Finance OS', text: reply.answer }])
      void loadDashboard()
      if (reply.intent?.includes('work_session') || activeNav === 'Horas') void loadWorkData()
      if (reply.intent === 'remember_commitment' || activeNav === 'Receitas') void loadMoneyData()
    } catch (err) {
      setMessages((current) => [
        ...current,
        {
          author: 'Finance OS',
          text: err instanceof Error ? `Falha ao falar com backend: ${err.message}` : 'Falha ao falar com backend.',
        },
      ])
    } finally {
      setBusy(false)
    }
  }

  const handleImport = async (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    setError('')
    try {
      const result = await importCsv(file)
      setMessages((current) => [
        ...current,
        {
          author: 'Finance OS',
          text: `CSV importado: ${result.imported} novos, ${result.duplicated} duplicados, ${result.skipped} ignorados.`,
        },
      ])
      await loadDashboard()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao importar CSV')
    } finally {
      setBusy(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleTransactionPatch = async (transaction: Transaction, patch: Partial<Transaction>) => {
    setBusy(true)
    setNotice('')
    try {
      const type = String(patch.transaction_type ?? transaction.transaction_type ?? 'expense')
      const isInternal = patch.is_internal ?? INTERNAL_TYPES.has(type)
      const result = await updateTransactionCategory(transaction.id, {
        category: String(patch.category ?? transaction.category),
        transaction_type: type,
        is_internal: isInternal,
      })
      setTransactions((current) =>
        current.map((item) =>
          item.id === transaction.id
            ? { ...item, category: result.category, transaction_type: result.transaction_type, is_internal: result.is_internal, category_locked: true }
            : item,
        ),
      )
      setNotice('Categoria salva. Essa transacao ficou protegida do reprocessamento.')
      void loadDashboard()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao salvar categoria')
    } finally {
      setBusy(false)
    }
  }

  const handleRuleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!ruleForm.pattern.trim()) return
    setBusy(true)
    setNotice('')
    try {
      await createCategoryRule({
        ...ruleForm,
        is_internal: ruleForm.is_internal || INTERNAL_TYPES.has(ruleForm.transaction_type),
      })
      setRuleForm((current) => ({ ...current, pattern: '' }))
      setNotice('Regra salva. Use reprocessar para aplicar em lancamentos antigos.')
      await loadRulesData()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao salvar regra')
    } finally {
      setBusy(false)
    }
  }

  const handleDeleteRule = async (rule: CategoryRule) => {
    if (!rule.id || rule.source !== 'custom') return
    setBusy(true)
    setNotice('')
    try {
      await deleteCategoryRule(rule.id)
      setNotice('Regra apagada.')
      await loadRulesData()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao apagar regra')
    } finally {
      setBusy(false)
    }
  }

  const handleReprocess = async () => {
    setBusy(true)
    setNotice('')
    try {
      const result = await reprocessTransactions()
      setNotice(`${result.updated} transacoes reprocessadas. Edicoes manuais preservadas.`)
      await Promise.all([loadDashboard(), loadRulesData()])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao reprocessar')
    } finally {
      setBusy(false)
    }
  }

  const handleWorkSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!workForm.date || !workForm.start || !workForm.end || !workForm.hourlyRate || busy) return
    const rate = Number(workForm.hourlyRate.replace(',', '.'))
    if (!Number.isFinite(rate) || rate <= 0) {
      setError('Valor/hora invalido')
      return
    }
    const text = `${workForm.date} trabalhei das ${workForm.start} ate ${workForm.end} ganhando R$ ${rate.toFixed(2)} por hora`
    setBusy(true)
    setNotice('')
    setError('')
    setMessages((current) => [...current, { author: 'Voce', text }])
    try {
      const reply = await askAgent(text)
      setMessages((current) => [...current, { author: 'Finance OS', text: reply.answer }])
      setNotice('Jornada salva no banco de horas.')
      setWorkForm((current) => ({ ...current, start: '', end: '' }))
      await Promise.all([loadDashboard(), loadWorkData()])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao salvar jornada')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="os-shell">
      <aside className="side-rail glass-sheet" aria-label="Navegacao">
        <a className="app-mark" href="#inicio" aria-label="Finance OS">
          <WalletCards size={20} />
        </a>
        <nav>
          {navItems.map((item) => (
            <button
              className={item.label === activeNav ? 'active' : ''}
              type="button"
              key={item.label}
              aria-label={item.label}
              onClick={() => setActiveNav(item.label)}
            >
              {item.icon}
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <button className="rail-button" type="button" aria-label="Atualizar" onClick={() => void loadDashboard()}>
          <Bell size={19} />
        </button>
      </aside>

      <section className="workspace" id="inicio">
        <header className="workspace-top glass-sheet">
          <div>
            <span>{todayLabel}</span>
            <strong>Finance OS</strong>
          </div>
          <div className="top-tools">
            <button type="button" onClick={() => void loadDashboard()}>
              <RefreshCw size={16} /> Atualizar
            </button>
            <button type="button" onClick={() => fileInputRef.current?.click()}>
              <Upload size={16} /> Importar CSV
            </button>
            <input
              ref={fileInputRef}
              aria-label="Importar CSV"
              hidden
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => void handleImport(event.target.files?.[0])}
            />
          </div>
        </header>

        {activeNav === 'Receitas' ? (
          <main className="money-grid">
            <section className="money-hero glass-panel">
              <div>
                <span>Livro financeiro</span>
                <h1>Receitas e despesas</h1>
                <p>Lancamentos reais mexem no saldo. Gastos fixos ficam como compromissos futuros ate voce registrar o pagamento.</p>
              </div>
              <button type="button" onClick={() => void loadMoneyData()} disabled={moneyLoading || busy}>
                <RefreshCw size={16} /> Atualizar
              </button>
              {(notice || error) && <p className={error ? 'rules-feedback danger' : 'rules-feedback'}>{error || notice}</p>}
            </section>

            <section className="money-kpis">
              <article className="metric-card glass-panel">
                <span><TrendingUp /></span>
                <div>
                  <p>Receitas registradas</p>
                  <strong>{money(summary?.kpis.income ?? moneyTotals.income)}</strong>
                  <small>entradas que ja contam no saldo</small>
                </div>
              </article>
              <article className="metric-card glass-panel">
                <span><TrendingDown /></span>
                <div>
                  <p>Despesas registradas</p>
                  <strong>{money(summary?.kpis.expenses ?? moneyTotals.expenses)}</strong>
                  <small>saidas reais do periodo</small>
                </div>
              </article>
              <article className="metric-card glass-panel">
                <span><CircleDollarSign /></span>
                <div>
                  <p>Fixos mensais</p>
                  <strong>{money(moneyTotals.fixedExpenses)}</strong>
                  <small>{money(moneyTotals.futureDebt)} futuro parcelado</small>
                </div>
              </article>
            </section>

            <section className="commitment-panel glass-panel">
              <div className="panel-title">
                <h2>Compromissos salvos</h2>
                <span>{commitments.length} ativos</span>
              </div>
              <div className="commitment-list">
                {commitments.map((item) => (
                  <article key={item.id}>
                    <div>
                      <span>{item.kind === 'income' ? 'receita fixa' : 'despesa fixa'} · {item.category}</span>
                      <strong>{item.description}</strong>
                      <p>
                        {item.installments_remaining
                          ? `${item.installments_remaining} parcelas restantes · total ${money(item.amount * item.installments_remaining)}`
                          : item.frequency === 'monthly'
                            ? 'mensal'
                            : item.frequency}
                        {item.due_day ? ` · vence dia ${item.due_day}` : ''}
                      </p>
                    </div>
                    <b className={item.kind === 'income' ? 'income' : 'expense'}>{money(item.amount)}</b>
                  </article>
                ))}
                {!commitments.length && (
                  <article className="empty-money">
                    <div>
                      <span>Nenhum compromisso fixo</span>
                      <strong>Ex.: gasto fixo de R$481,60 parcela celular, 11 parcelas restantes</strong>
                    </div>
                  </article>
                )}
              </div>
            </section>

            <section className="money-transactions glass-panel">
              <div className="panel-title">
                <h2>Lancamentos</h2>
                <span>{transactions.length} recentes</span>
              </div>
              <div className="money-table">
                <div className="money-table-head">
                  <span>Data</span>
                  <span>Descricao</span>
                  <span>Categoria</span>
                  <span>Valor</span>
                </div>
                {transactions.map((transaction) => (
                  <article key={transaction.id}>
                    <span>{formatDate(transaction.date)}</span>
                    <strong>{transaction.description}</strong>
                    <span>{transaction.category}</span>
                    <b className={transaction.amount >= 0 ? 'income' : 'expense'}>{money(transaction.amount)}</b>
                  </article>
                ))}
                {!transactions.length && (
                  <article className="empty-row">
                    <strong>Sem lancamentos ainda</strong>
                    <small>Registre pelo chat: ganhei R$250, gastei R$80 no mercado.</small>
                  </article>
                )}
              </div>
            </section>
          </main>
        ) : activeNav === 'Regras' ? (
          <main className="rules-grid">
            <section className="rules-hero glass-panel">
              <div>
                <span>Controle de dados</span>
                <h1>Categorias e regras</h1>
                <p>Corrija uma transacao, crie uma palavra-chave e reprocesse os lancamentos antigos sem apagar suas edicoes manuais.</p>
              </div>
              <div className="rules-actions">
                <button type="button" onClick={() => void loadRulesData()} disabled={rulesLoading || busy}>
                  <RefreshCw size={16} /> Atualizar
                </button>
                <button type="button" onClick={() => void handleReprocess()} disabled={rulesLoading || busy}>
                  <RotateCcw size={16} /> Reprocessar
                </button>
              </div>
              {(notice || error) && <p className={error ? 'rules-feedback danger' : 'rules-feedback'}>{error || notice}</p>}
            </section>

            <section className="rules-transactions glass-panel">
              <div className="panel-title">
                <h2>Transacoes recentes</h2>
                <span>{transactions.length} itens</span>
              </div>
              <div className="rules-table" aria-label="Editar categorias de transacoes">
                <div className="rules-table-head">
                  <span>Data</span>
                  <span>Descricao</span>
                  <span>Categoria</span>
                  <span>Tipo</span>
                </div>
                {transactions.map((transaction) => (
                  <article key={transaction.id}>
                    <span>{transaction.date.slice(5)}</span>
                    <strong title={transaction.description}>{transaction.description}</strong>
                    <label>
                      <span>Categoria</span>
                      <select
                        value={transaction.category}
                        onChange={(event) => void handleTransactionPatch(transaction, { category: event.target.value })}
                        disabled={busy}
                      >
                        {categoryOptions.map((category) => (
                          <option key={category} value={category}>{category}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      <span>Tipo</span>
                      <select
                        value={transaction.transaction_type ?? 'expense'}
                        onChange={(event) => void handleTransactionPatch(transaction, { transaction_type: event.target.value })}
                        disabled={busy}
                      >
                        {TRANSACTION_TYPES.map((type) => (
                          <option key={type.value} value={type.value}>{type.label}</option>
                        ))}
                      </select>
                    </label>
                    <small>{transaction.category_locked ? 'manual' : 'auto'} · {money(transaction.amount)}</small>
                  </article>
                ))}
                {!transactions.length && (
                  <article className="empty-row">
                    <strong>Nenhuma transacao ainda</strong>
                    <small>Importe CSV ou registre pelo chat.</small>
                  </article>
                )}
              </div>
            </section>

            <form className="rule-form glass-panel" onSubmit={handleRuleSubmit}>
              <div className="panel-title">
                <h2>Nova regra</h2>
                <span>palavra-chave</span>
              </div>
              <label>
                Palavra ou texto da descricao
                <input
                  value={ruleForm.pattern}
                  placeholder="Ex.: academia, nubank, ifood"
                  onChange={(event) => setRuleForm((current) => ({ ...current, pattern: event.target.value }))}
                />
              </label>
              <label>
                Categoria
                <select
                  value={ruleForm.category}
                  onChange={(event) => setRuleForm((current) => ({ ...current, category: event.target.value }))}
                >
                  {categoryOptions.map((category) => (
                    <option key={category} value={category}>{category}</option>
                  ))}
                </select>
              </label>
              <label>
                Tipo financeiro
                <select
                  value={ruleForm.transaction_type}
                  onChange={(event) =>
                    setRuleForm((current) => ({
                      ...current,
                      transaction_type: event.target.value,
                      is_internal: INTERNAL_TYPES.has(event.target.value),
                    }))
                  }
                >
                  {TRANSACTION_TYPES.map((type) => (
                    <option key={type.value} value={type.value}>{type.label}</option>
                  ))}
                </select>
              </label>
              <label className="check-line">
                <input
                  type="checkbox"
                  checked={ruleForm.is_internal}
                  onChange={(event) => setRuleForm((current) => ({ ...current, is_internal: event.target.checked }))}
                />
                Nao contar no fluxo real
              </label>
              <button type="submit" disabled={busy || !ruleForm.pattern.trim()}>
                <Save size={16} /> Salvar regra
              </button>
            </form>

            <section className="rule-library glass-panel">
              <div className="panel-title">
                <h2>Biblioteca</h2>
                <span>{categoryRules.filter((rule) => rule.source === 'custom').length} pessoais</span>
              </div>
              <div className="rule-list">
                {categoryRules.map((rule) => (
                  <article key={`${rule.source}-${rule.id ?? rule.category}`}>
                    <div>
                      <span>{rule.source === 'custom' ? 'pessoal' : 'sistema'} · {rule.transaction_type}</span>
                      <strong>{rule.category}</strong>
                      <p>{rule.patterns.slice(0, 5).join(', ')}</p>
                    </div>
                    {rule.source === 'custom' && rule.id ? (
                      <button type="button" aria-label={`Apagar regra ${rule.pattern}`} onClick={() => void handleDeleteRule(rule)} disabled={busy}>
                        <Trash2 size={16} />
                      </button>
                    ) : (
                      <small>fixa</small>
                    )}
                  </article>
                ))}
              </div>
            </section>
          </main>
        ) : activeNav === 'Horas' ? (
          <main className="work-grid">
            <section className="work-hero glass-panel">
              <div>
                <span>Banco de horas</span>
                <h1>Horas e ganhos por dia</h1>
                <p>Registro real das jornadas que voce salvou pelo chat ou pelo formulario. Cada linha mostra o que ficou no banco.</p>
              </div>
              <button type="button" onClick={() => void loadWorkData()} disabled={workLoading || busy}>
                <RefreshCw size={16} /> Atualizar
              </button>
              {(notice || error) && <p className={error ? 'rules-feedback danger' : 'rules-feedback'}>{error || notice}</p>}
            </section>

            <section className="work-kpis">
              <article className="metric-card glass-panel">
                <span><Clock3 /></span>
                <div>
                  <p>Total de horas</p>
                  <strong>{workTotals.hours.toFixed(2)}h</strong>
                  <small>{workTotals.days} dias registrados</small>
                </div>
              </article>
              <article className="metric-card glass-panel">
                <span><CircleDollarSign /></span>
                <div>
                  <p>Total ganho</p>
                  <strong>{money(workTotals.gross)}</strong>
                  <small>receita criada pelas jornadas</small>
                </div>
              </article>
              <article className="metric-card glass-panel">
                <span><TrendingUp /></span>
                <div>
                  <p>Media por hora</p>
                  <strong>{money(workTotals.averageRate)}</strong>
                  <small>baseado nos registros salvos</small>
                </div>
              </article>
            </section>

            <form className="work-form glass-panel" onSubmit={handleWorkSubmit}>
              <div className="panel-title">
                <h2>Registrar jornada</h2>
                <span>usa IA</span>
              </div>
              <label>
                Data
                <input
                  type="date"
                  value={workForm.date}
                  onChange={(event) => setWorkForm((current) => ({ ...current, date: event.target.value }))}
                />
              </label>
              <div className="work-form-row">
                <label>
                  Entrada
                  <input
                    type="time"
                    value={workForm.start}
                    onChange={(event) => setWorkForm((current) => ({ ...current, start: event.target.value }))}
                  />
                </label>
                <label>
                  Saida
                  <input
                    type="time"
                    value={workForm.end}
                    onChange={(event) => setWorkForm((current) => ({ ...current, end: event.target.value }))}
                  />
                </label>
              </div>
              <label>
                Valor/hora
                <input
                  inputMode="decimal"
                  value={workForm.hourlyRate}
                  placeholder="Ex.: 12"
                  onChange={(event) => setWorkForm((current) => ({ ...current, hourlyRate: event.target.value }))}
                />
              </label>
              <button type="submit" disabled={busy || !workForm.date || !workForm.start || !workForm.end || !workForm.hourlyRate}>
                <Save size={16} /> Salvar jornada
              </button>
            </form>

            <section className="work-days glass-panel">
              <div className="panel-title">
                <h2>Por dia</h2>
                <span>{workDays.length} dias</span>
              </div>
              <div className="work-day-list">
                {workDays.map((day) => (
                  <article key={day.date}>
                    <div>
                      <span>{formatDate(day.date)}</span>
                      <strong>{day.hours.toFixed(2)}h</strong>
                    </div>
                    <div>
                      <span>{day.count} jornada{day.count > 1 ? 's' : ''}</span>
                      <strong>{money(day.gross)}</strong>
                    </div>
                  </article>
                ))}
                {!workDays.length && (
                  <article className="empty-work">
                    <div>
                      <span>Nenhuma jornada salva</span>
                      <strong>Registre pelo chat ou formulario</strong>
                    </div>
                  </article>
                )}
              </div>
            </section>

            <section className="work-sessions glass-panel">
              <div className="panel-title">
                <h2>Jornadas salvas</h2>
                <span>{workSessions.length} registros</span>
              </div>
              <div className="work-table">
                <div className="work-table-head">
                  <span>Data</span>
                  <span>Horario</span>
                  <span>Horas</span>
                  <span>Valor/h</span>
                  <span>Total</span>
                </div>
                {workSessions.map((session) => (
                  <article key={session.id}>
                    <span>{formatDate(session.date)}</span>
                    <strong>{session.start_time && session.end_time ? `${session.start_time}-${session.end_time}` : 'sem horario'}</strong>
                    <b>{Number(session.hours).toFixed(2)}h</b>
                    <b>{money(session.hourly_rate)}</b>
                    <b>{money(session.gross_amount)}</b>
                    <small>{session.description}</small>
                  </article>
                ))}
                {!workSessions.length && (
                  <article className="empty-row">
                    <strong>Sem banco de horas ainda</strong>
                    <small>Ex.: trabalhei das 13:30 ate 17:30 ganhando R$12 por hora.</small>
                  </article>
                )}
              </div>
            </section>
          </main>
        ) : (
        <main className="personal-grid">
          <section className="assistant-pane glass-panel" aria-label="Agente financeiro pessoal">
            <div className="assistant-head">
              <span className="agent-avatar"><Bot size={22} /></span>
              <div>
                <h1>Bom dia, Lukas.</h1>
                <p>
                  {error
                    ? 'Backend indisponivel. Verifique Render e variaveis.'
                    : summary
                      ? summary.recentTransactions.length
                        ? `Revisei ${summary.recentTransactions.length} lancamentos recentes e ${summary.actionPlan.length} acoes.`
                        : 'Sem dados pessoais ainda. Registre receitas e despesas pelo chat.'
                      : 'Conectando ao backend financeiro...'}
                </p>
              </div>
            </div>

            <div className="status-row">
              <span><Sparkles size={15} /> {summary?.insights.length ?? 0} sinais</span>
              <span><ShieldAlert size={15} /> risco {summary?.kpis.cashRisk ?? '...'}</span>
              <span><Clock3 size={15} /> {loading || busy ? 'sincronizando' : 'online'}</span>
            </div>

            <div className="chat-window">
              {messages.map((message, index) => (
                <article className={message.author === 'Voce' ? 'message user' : 'message agent'} key={`${message.text}-${index}`}>
                  <span>{message.author}</span>
                  <p>{message.text}</p>
                </article>
              ))}
            </div>

            <form className="ask-box" onSubmit={handleAsk}>
              <label htmlFor="ask-agent">Perguntar ao financeiro</label>
              <div>
                <Search size={18} />
                <input
                  id="ask-agent"
                  type="text"
                  value={question}
                  placeholder="Ex.: hoje ganhei R$250"
                  onChange={(event) => setQuestion(event.target.value)}
                />
                <button type="submit" aria-label="Enviar pergunta" disabled={busy}>
                  <Send size={18} />
                </button>
              </div>
            </form>
          </section>

          <aside className="right-column">
            <section className="balance-card glass-panel">
              <div className="panel-title">
                <h2>Resumo</h2>
                <button type="button" onClick={() => void loadDashboard()}><SlidersHorizontal size={15} /> Recarregar</button>
              </div>
              <strong>{money(summary?.kpis.balance)}</strong>
              <p>{summary?.recentTransactions.length ? 'saldo atual pelos seus lancamentos' : 'sem lancamentos pessoais ainda'}</p>
              <div className="mini-line" aria-label="Fluxo projetado">
                {(summary?.monthlySeries.slice(-6) ?? []).map((point) => (
                  <i key={point.month} style={{ height: `${Math.max(18, Math.min(58, Math.abs(point.net) / 180))}px` }} />
                ))}
                {!summary && [24, 35, 28, 44, 38, 52].map((height) => <i key={height} style={{ height }} />)}
              </div>
            </section>

            <section className="decision-card glass-panel">
              <div className="panel-title">
                <h2>Decisoes</h2>
                <span>{activeNav.toLowerCase()}</span>
              </div>
              <div className="decision-list">
                {decisions.map((item) => (
                  <article key={item.title}>
                    <div>
                      <strong>{item.title}</strong>
                      <p>{item.detail}</p>
                    </div>
                    <span>{item.state}</span>
                  </article>
                ))}
                {!decisions.length && (
                  <article>
                    <div>
                      <strong>Sem dados ainda</strong>
                      <p>Registre receita ou despesa pelo chat para gerar analise.</p>
                    </div>
                    <span>vazio</span>
                  </article>
                )}
              </div>
            </section>
          </aside>

          <section className="glass-panel risk-panel">
            <div className="panel-title">
              <h2>Risco de caixa</h2>
              <span>{summary?.kpis.riskLevel ?? 'sync'}</span>
            </div>
            <div className="risk-list">
              {riskRows.map((row) => (
                <div className="risk-row" key={row.name}>
                  <span>{row.name}</span>
                  <div><i style={{ width: row.width }} /></div>
                  <b>{row.value}</b>
                </div>
              ))}
            </div>
          </section>

          <section className="card-strip">
            {cards.map((card) => (
              <article className="metric-card glass-panel" key={card.label}>
                <span>{card.icon}</span>
                <div>
                  <p>{card.label}</p>
                  <strong>{card.value}</strong>
                  <small>{card.hint}</small>
                </div>
              </article>
            ))}
          </section>

          <section className="glass-panel notes-panel">
            <div className="panel-title">
              <h2>Livro caixa</h2>
              <MessageCircle size={17} />
            </div>
            <p>
              {summary?.recentTransactions.length
                ? (summary?.insights[0]?.message ?? 'Dados pessoais carregados.')
                : (error || 'Sem dados pessoais. Ex.: hoje ganhei R$250, gastei R$80 no mercado.')}
            </p>
            <div className="ledger-list" aria-label="Lancamentos recentes">
              {(summary?.recentTransactions.slice(0, 5) ?? []).map((transaction) => (
                <article key={transaction.id}>
                  <span>{transaction.date.slice(5)} · {transaction.category}</span>
                  <strong>{transaction.description}</strong>
                  <b className={transaction.amount >= 0 ? 'income' : 'expense'}>
                    {money(transaction.amount)}
                  </b>
                </article>
              ))}
            </div>
          </section>
        </main>
        )}
      </section>
    </div>
  )
}

export default App
