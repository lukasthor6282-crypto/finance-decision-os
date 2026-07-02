import type { FormEvent } from 'react'
import type { CategoryRule, FinanceSummary, Transaction } from './types'
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
  getSummary,
  getTransactions,
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
  { label: 'Fluxo', icon: <TrendingUp size={19} /> },
  { label: 'Categorias', icon: <PieChart size={19} /> },
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
  const [categoryRules, setCategoryRules] = useState<CategoryRule[]>([])
  const [rulesLoading, setRulesLoading] = useState(false)
  const [notice, setNotice] = useState('')
  const [ruleForm, setRuleForm] = useState({
    pattern: '',
    category: 'Alimentacao',
    transaction_type: 'expense',
    is_internal: false,
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

  useEffect(() => {
    if (activeNav === 'Regras') void loadRulesData()
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

        {activeNav === 'Regras' ? (
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
