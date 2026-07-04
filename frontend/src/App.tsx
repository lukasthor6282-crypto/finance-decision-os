import type { CSSProperties, FormEvent } from 'react'
import type { CategoryRule, Commitment, FinanceSummary, ImportMapping, ImportPreview, Transaction, WorkSession } from './types'
import {
  AlertTriangle,
  BarChart3,
  Bell,
  Bot,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  CreditCard,
  Database,
  Download,
  Goal,
  Grid2X2,
  Landmark,
  PieChart,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Send,
  Settings,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  Tags,
  TrendingDown,
  TrendingUp,
  Trash2,
  Upload,
  WalletCards,
  Zap,
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
  importStatement,
  previewImport,
  reprocessTransactions,
  updateTransactionCategory,
} from './api'
import './App.css'

type ChatMessage = {
  author: 'Finance OS' | 'Voce'
  text: string
}

const navItems = [
  { label: 'Painel financeiro', icon: <Grid2X2 size={18} /> },
  { label: 'Transacoes', icon: <SlidersHorizontal size={18} /> },
  { label: 'Receitas & Despesas', icon: <CircleDollarSign size={18} /> },
  { label: 'Metas', icon: <Goal size={18} /> },
  { label: 'Banco de horas', icon: <Clock3 size={18} /> },
  { label: 'Planejamento', icon: <CalendarDays size={18} /> },
  { label: 'Relatorios', icon: <BarChart3 size={18} /> },
  { label: 'Categorias', icon: <Tags size={18} /> },
  { label: 'Importacoes', icon: <Download size={18} /> },
  { label: 'Configuracoes', icon: <Settings size={18} /> },
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

const IMPORT_FIELDS: Array<{ key: keyof ImportMapping; label: string; required?: boolean }> = [
  { key: 'date', label: 'Data', required: true },
  { key: 'description', label: 'Descricao', required: true },
  { key: 'amount', label: 'Valor', required: true },
  { key: 'account', label: 'Banco/conta' },
  { key: 'transaction_type', label: 'Tipo' },
  { key: 'payment_method', label: 'Forma de pagamento' },
  { key: 'category', label: 'Categoria' },
  { key: 'notes', label: 'Observacao' },
]

function App() {
  const [summary, setSummary] = useState<FinanceSummary | null>(null)
  const [, setMessages] = useState<ChatMessage[]>(fallbackMessages)
  const [question, setQuestion] = useState('')
  const [activeNav, setActiveNav] = useState('Painel financeiro')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [workSessions, setWorkSessions] = useState<WorkSession[]>([])
  const [commitments, setCommitments] = useState<Commitment[]>([])
  const [categoryRules, setCategoryRules] = useState<CategoryRule[]>([])
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null)
  const [importMapping, setImportMapping] = useState<ImportMapping>({})
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
    if (activeNav === 'Categorias' || activeNav === 'Configuracoes') void loadRulesData()
    if (activeNav === 'Banco de horas') void loadWorkData()
    if (activeNav === 'Receitas & Despesas' || activeNav === 'Transacoes') void loadMoneyData()
  }, [activeNav])

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

  const dashboardAlerts = useMemo(() => {
    if (summary?.alerts.length) {
      return summary.alerts.slice(0, 3).map((alert) => ({
        tone: alert.severity === 'high' ? 'danger' : alert.severity === 'medium' ? 'warning' : 'info',
        title: alert.title,
        message: alert.message,
      }))
    }
    return [
      {
        tone: 'info',
        title: 'Sem alertas criticos',
        message: 'Quando houver dados suficientes, os riscos aparecem aqui.',
      },
    ]
  }, [summary])

  const flowBars = useMemo(() => {
    const series = summary?.monthlySeries.slice(-10) ?? []
    if (series.length) {
      return series.map((point) => ({
        height: Math.max(14, Math.min(70, Math.abs(point.net) / 120)),
        negative: point.net < 0,
      }))
    }
    return [16, 22, 19, 28, 24, 34, 21, 30, 38, 44].map((height) => ({ height, negative: false }))
  }, [summary])

  const monthBars = useMemo(() => {
    const seed = [9, 14, 8, 22, 11, 18, 7, 10, 28, 12, 5, 9, 16, 7, 13, 8, 24, 20, 11, 7, 14, 17, 8, 10, 22, 15, 9, 6, 13, 19, 31]
    return seed.map((height, index) => ({
      height,
      negative: index % 5 === 1 || index % 7 === 0,
    }))
  }, [])

  const goalProgress = Math.max(0, Math.min(100, summary?.goals[0]?.progress ?? 0))
  const healthScore = Math.max(0, Math.min(100, summary?.kpis.healthScore ?? 0))

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
      if (reply.intent?.includes('work_session') || activeNav === 'Banco de horas') void loadWorkData()
      if (reply.intent === 'remember_commitment' || activeNav === 'Receitas & Despesas' || activeNav === 'Transacoes') void loadMoneyData()
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

  const handleImportPreview = async (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const preview = await previewImport(file)
      setImportFile(file)
      setImportPreview(preview)
      setImportMapping(preview.detectedMapping ?? {})
      setNotice('Colunas lidas. Confira o mapeamento antes de importar.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao ler extrato')
    } finally {
      setBusy(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleFileSelected = async (file: File | undefined) => {
    if (!file) return
    if (activeNav === 'Importacoes') {
      await handleImportPreview(file)
      return
    }
    await handleImport(file)
  }

  const handleImport = async (file: File | undefined, mapping: ImportMapping = {}) => {
    if (!file) return
    setBusy(true)
    setError('')
    try {
      const result = await importStatement(file, mapping)
      setMessages((current) => [
        ...current,
        {
          author: 'Finance OS',
          text: `Extrato importado: ${result.imported} novos, ${result.duplicated} duplicados, ${result.skipped} ignorados.`,
        },
      ])
      setNotice(`Importado: ${result.imported} novos, ${result.duplicated} duplicados, ${result.skipped} ignorados.`)
      if (result.errors?.length) setError(result.errors.slice(0, 3).join(' | '))
      await loadDashboard()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao importar extrato')
    } finally {
      setBusy(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const handleMappedImport = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!importFile) {
      setError('Selecione um CSV ou Excel primeiro.')
      return
    }
    await handleImport(importFile, importMapping)
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
          <span>Finance OS</span>
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
            <span>Visao geral da sua vida financeira</span>
            <strong>Painel financeiro</strong>
          </div>
          <div className="top-tools">
            <button type="button" className="month-button" onClick={() => void loadDashboard()}>
              <CalendarDays size={16} /> Julho de 2026 <ChevronDown size={15} />
            </button>
            <button type="button" className="icon-button" aria-label="Notificacoes" onClick={() => void loadDashboard()}>
              <Bell size={16} />
            </button>
            <input
              ref={fileInputRef}
              aria-label="Importar extrato"
              hidden
              type="file"
              accept=".csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
              onChange={(event) => void handleFileSelected(event.target.files?.[0])}
            />
          </div>
        </header>

        {activeNav === 'Receitas & Despesas' || activeNav === 'Transacoes' ? (
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
                      <span>{item.kind === 'income' ? 'receita fixa' : 'despesa fixa'} - {item.category}</span>
                      <strong>{item.description}</strong>
                      <p>
                        {item.installments_remaining
                          ? `${item.installments_remaining} parcelas restantes - total ${money(item.amount * item.installments_remaining)}`
                          : item.frequency === 'monthly'
                            ? 'mensal'
                            : item.frequency}
                        {item.due_day ? ` - vence dia ${item.due_day}` : ''}
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
        ) : activeNav === 'Categorias' || activeNav === 'Configuracoes' ? (
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
                    <small>{transaction.category_locked ? 'manual' : 'auto'} - {money(transaction.amount)}</small>
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
                      <span>{rule.source === 'custom' ? 'pessoal' : 'sistema'} - {rule.transaction_type}</span>
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
        ) : activeNav === 'Banco de horas' ? (
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
        ) : activeNav === 'Importacoes' ? (
          <main className="data-grid">
            <section className="data-hero glass-panel">
              <div>
                <span>Importacao de extratos</span>
                <h1>Dados financeiros</h1>
                <p>Importe CSV ou Excel, confira as colunas e mapeie os campos antes de gravar no banco.</p>
              </div>
              <button type="button" onClick={() => fileInputRef.current?.click()} disabled={busy}>
                <Upload size={16} /> Selecionar arquivo
              </button>
              {(notice || error) && <p className={error ? 'rules-feedback danger' : 'rules-feedback'}>{error || notice}</p>}
            </section>

            <form className="data-mapping glass-panel" onSubmit={handleMappedImport}>
              <div className="panel-title">
                <h2>Mapeamento</h2>
                <span>{importFile?.name ?? 'sem arquivo'}</span>
              </div>
              <div className="mapping-grid">
                {IMPORT_FIELDS.map((field) => (
                  <label key={field.key}>
                    {field.label}{field.required ? ' *' : ''}
                    <select
                      value={importMapping[field.key] ?? ''}
                      onChange={(event) =>
                        setImportMapping((current) => ({
                          ...current,
                          [field.key]: event.target.value || null,
                        }))
                      }
                      disabled={!importPreview || busy}
                    >
                      <option value="">Nao usar</option>
                      {importPreview?.columns.map((column) => (
                        <option key={column} value={column}>{column}</option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
              <button type="submit" disabled={!importFile || busy}>
                <Upload size={16} /> Importar para o banco
              </button>
            </form>

            <section className="data-preview glass-panel">
              <div className="panel-title">
                <h2>Previa</h2>
                <span>{importPreview?.sampleRows.length ?? 0} linhas</span>
              </div>
              {importPreview ? (
                <div className="preview-table">
                  <div
                    className="preview-head"
                    style={{ gridTemplateColumns: `repeat(${Math.max(1, Math.min(importPreview.columns.length, 5))}, minmax(120px, 1fr))` }}
                  >
                    {importPreview.columns.slice(0, 5).map((column) => <span key={column}>{column}</span>)}
                  </div>
                  {importPreview.sampleRows.map((row, index) => (
                    <article
                      key={`${index}-${row[importPreview.columns[0]] ?? 'linha'}`}
                      style={{ gridTemplateColumns: `repeat(${Math.max(1, Math.min(importPreview.columns.length, 5))}, minmax(120px, 1fr))` }}
                    >
                      {importPreview.columns.slice(0, 5).map((column) => <span key={column}>{row[column]}</span>)}
                    </article>
                  ))}
                </div>
              ) : (
                <article className="empty-row">
                  <strong>Nenhum arquivo selecionado</strong>
                  <small>Use CSV, XLS ou XLSX. O sistema tenta detectar data, descricao e valor automaticamente.</small>
                </article>
              )}
            </section>

            <section className="data-rules glass-panel">
              <div className="panel-title">
                <h2>Padrao esperado</h2>
                <Database size={17} />
              </div>
              <div className="data-checklist">
                <article>
                  <strong>Obrigatorio</strong>
                  <span>Data, descricao e valor.</span>
                </article>
                <article>
                  <strong>Opcional</strong>
                  <span>Banco, tipo, forma de pagamento, categoria e observacao.</span>
                </article>
                <article>
                  <strong>Privado</strong>
                  <span>O extrato nao vai para IA. Python importa, valida e calcula.</span>
                </article>
              </div>
            </section>
          </main>
        ) : (
        <main className="personal-grid">
          <section className="balance-card glass-panel">
            <div className="panel-title">
              <div>
                <h2>Saldo livre</h2>
                <span>{loading ? 'Sincronizando' : 'Atualizado agora'}</span>
              </div>
              <button type="button" className="icon-button soft" onClick={() => void loadDashboard()} aria-label="Atualizar saldo">
                <RefreshCw size={16} />
              </button>
            </div>
            <strong>{money(summary?.kpis.balance)}</strong>
            <p>Disponivel para uso</p>
            <small className={summary && summary.kpis.net < 0 ? 'delta down' : 'delta'}>{money(summary?.kpis.net)} no mes</small>
            <div className="balance-chart" aria-label="Fluxo recente">
              {flowBars.map((bar, index) => (
                <i key={`${bar.height}-${index}`} className={bar.negative ? 'negative' : ''} style={{ height: `${bar.height}px` }} />
              ))}
            </div>
            <div className="chart-scale">
              <span>30 Jun</span>
              <span>Hoje</span>
            </div>
          </section>

          <section className="assistant-pane glass-panel" aria-label="IA financeira">
            <div className="panel-title">
              <div>
                <h2>IA financeira</h2>
                <span>Seu assistente financeiro pessoal</span>
              </div>
              <button type="button" className="icon-button soft" onClick={() => void loadDashboard()} aria-label="Sincronizar IA">
                <RefreshCw size={16} />
              </button>
            </div>

            <div className="assistant-orb" aria-hidden="true">
              <Bot size={42} />
            </div>

            <div className="quick-prompts">
              {[
                ['Qual meu saldo projetado ate o fim do mes?', <Landmark size={15} />],
                ['Posso comprar um celular de R$ 2.400 em 10x?', <CreditCard size={15} />],
                ['Onde estou gastando mais este mes?', <PieChart size={15} />],
                ['Qual o melhor plano para comprar um BYD King?', <Goal size={15} />],
              ].map(([label, icon]) => (
                <button type="button" key={String(label)} onClick={() => setQuestion(String(label))}>
                  <span>{icon}</span>
                  {label}
                  <ChevronRight size={15} />
                </button>
              ))}
            </div>

            <form className="ask-box" onSubmit={handleAsk}>
              <div>
                <input
                  id="ask-agent"
                  type="text"
                  value={question}
                  placeholder="Pergunte algo..."
                  onChange={(event) => setQuestion(event.target.value)}
                />
                <button type="submit" aria-label="Enviar pergunta" disabled={busy}>
                  <Send size={17} />
                </button>
              </div>
            </form>
          </section>

          <section className="hours-card glass-panel">
            <div className="panel-title">
              <div>
                <h2>Banco de horas</h2>
                <span>Saldo de horas</span>
              </div>
              <Clock3 size={18} />
            </div>
            <strong>{workTotals.hours.toFixed(2)}h</strong>
            <p>Horas trabalhadas registradas</p>
            <div className="progress-line"><i style={{ width: `${Math.min(100, Math.max(6, workTotals.hours))}%` }} /></div>
            <small>{workTotals.days} dias salvos</small>
          </section>

          <section className="alerts-panel glass-panel">
            <div className="panel-title">
              <h2>Alertas</h2>
              <AlertTriangle size={18} />
            </div>
            <div className="alert-list">
              {dashboardAlerts.map((alert) => (
                <article className={alert.tone} key={alert.title}>
                  <strong>{alert.title}</strong>
                  <p>{alert.message}</p>
                </article>
              ))}
            </div>
            <button type="button" className="ghost-row">Ver todos os alertas <ChevronRight size={15} /></button>
          </section>

          <section className="glass-panel risk-panel">
            <div className="panel-title">
              <h2>Risco de caixa</h2>
              <ShieldAlert size={18} />
            </div>
            <div className="risk-gauge" style={{ '--score': `${healthScore}%` } as CSSProperties}>
              <strong>{healthScore}%</strong>
              <span>{summary?.kpis.cashRisk ?? 'Sem dados'}</span>
            </div>
            <p>Sua saude financeira aparece aqui depois dos lancamentos.</p>
          </section>

          <section className="plan-card glass-panel">
            <div className="panel-title">
              <div>
                <h2>Plano estrategico</h2>
                <span>{summary?.goals[0]?.name ?? 'Meta principal'}</span>
              </div>
              <TrendingUp size={18} />
            </div>
            <div className="plan-body">
              <div className="plan-ring" style={{ '--score': `${goalProgress}%` } as CSSProperties}>
                <strong>{Math.round(goalProgress)}%</strong>
              </div>
              <div>
                <span>Guardado</span>
                <strong>{money(summary?.goals[0]?.current_amount ?? 0)}</strong>
                <p>de {money(summary?.goals[0]?.target_amount ?? 0)}</p>
              </div>
            </div>
            <small>{summary?.goals[0]?.monthlyRequired ? `${money(summary.goals[0].monthlyRequired)} por mes` : 'Cadastre uma meta para calcular prazo.'}</small>
          </section>

          <section className="transactions-panel glass-panel">
            <div className="panel-title">
              <h2>Transacoes recentes</h2>
              <button type="button" onClick={() => setActiveNav('Transacoes')}>Ver todas</button>
            </div>
            <div className="dashboard-table">
              <div>
                <span>Data</span>
                <span>Descricao</span>
                <span>Categoria</span>
                <span>Tipo</span>
                <span>Valor</span>
                <span>Saldo</span>
              </div>
              {(summary?.recentTransactions.slice(0, 5) ?? []).map((transaction) => (
                <article key={transaction.id}>
                  <span>{formatDate(transaction.date)}</span>
                  <strong>{transaction.description}</strong>
                  <span>{transaction.category}</span>
                  <span>{transaction.transaction_type ?? 'Lancamento'}</span>
                  <b className={transaction.amount >= 0 ? 'income' : 'expense'}>{money(transaction.amount)}</b>
                  <span>{money(summary?.kpis.balance)}</span>
                </article>
              ))}
              {!summary?.recentTransactions.length && (
                <article className="empty-row">
                  <strong>Sem transacoes ainda</strong>
                  <small>Registre pelo chat ou importe um extrato.</small>
                </article>
              )}
            </div>
          </section>

          <section className="month-card glass-panel">
            <div className="panel-title">
              <h2>Resumo do mes</h2>
              <button type="button">Ver relatorio <ChevronDown size={14} /></button>
            </div>
            <div className="month-lines">
              <span><CircleDollarSign size={14} /> Receitas <b className="income">{money(summary?.kpis.income)}</b></span>
              <span><TrendingDown size={14} /> Despesas <b className="expense">{money(summary?.kpis.expenses)}</b></span>
              <span><Landmark size={14} /> Saldo liquido <b className={summary && summary.kpis.net < 0 ? 'expense' : 'income'}>{money(summary?.kpis.net)}</b></span>
            </div>
            <div className="month-chart">
              {monthBars.map((bar, index) => (
                <i key={`${bar.height}-${index}`} className={bar.negative ? 'negative' : ''} style={{ height: `${bar.height}px` }} />
              ))}
            </div>
          </section>

          <nav className="dock-nav" aria-label="Atalhos do painel">
            <button type="button" className="active"><Grid2X2 size={18} /> Visao geral</button>
            <button type="button"><PieChart size={18} /> Analises</button>
            <button type="button" className="dock-plus" onClick={() => setQuestion('Registrar novo lancamento')}><Plus size={24} /></button>
            <button type="button"><Sparkles size={18} /> Insights</button>
            <button type="button"><Zap size={18} /> Atalhos</button>
          </nav>
        </main>
        )}
      </section>
    </div>
  )
}

export default App
