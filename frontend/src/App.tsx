import { useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties, FormEvent, ReactNode, RefObject } from 'react'
import {
  Bell,
  Calendar,
  CheckCircle2,
  ChevronDown,
  Clock3,
  CreditCard,
  Eye,
  FileClock,
  Grid2X2,
  ListChecks,
  Loader2,
  MessageCircle,
  MoreHorizontal,
  ReceiptText,
  Send,
  ShieldCheck,
  Sun,
  Wallet,
  Zap,
} from 'lucide-react'
import { askAgent, getSimpleSummary } from './api'
import type { SimpleEntry, SimpleInvoice, SimpleSummary } from './types'
import './App.css'

type ChatMessage = {
  author: 'Finance OS' | 'Voce'
  text: string
}

type RailSection = 'daily' | 'invoices' | 'pending' | 'recent' | 'chat'

const starterMessages: ChatMessage[] = [
  {
    author: 'Finance OS',
    text: 'Pronto. Escreva frases simples: ganhei R$ 250, gastei R$ 40 no mercado, tenho R$ 120 de internet para pagar.',
  },
]

const money = (value = 0) =>
  new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value)

const formatDate = (value: string) => {
  const parsed = new Date(`${value}T12:00:00`)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit' }).format(parsed)
}

const formatMonth = (value?: string) => {
  if (!value) return 'Julho de 2026'
  const [year, month] = value.split('-').map(Number)
  return new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric' }).format(new Date(year, month - 1, 1))
}

const formatWorkHours = (value = 0) => {
  const hours = Math.floor(value)
  const minutes = Math.round((value - hours) * 60)
  if (!minutes) return `${hours}h`
  return `${hours}h${String(minutes).padStart(2, '0')}`
}

function App() {
  const [summary, setSummary] = useState<SimpleSummary | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>(starterMessages)
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [activeSection, setActiveSection] = useState<RailSection>('daily')

  const inputRef = useRef<HTMLInputElement>(null)
  const dailyRef = useRef<HTMLElement>(null)
  const invoiceRef = useRef<HTMLElement>(null)
  const pendingRef = useRef<HTMLElement>(null)
  const recentRef = useRef<HTMLElement>(null)
  const chatRef = useRef<HTMLElement>(null)

  const loadSummary = async () => {
    setError('')
    setLoading(true)
    try {
      setSummary(await getSimpleSummary())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao carregar dados')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadSummary()
  }, [])

  const totals = summary?.totals
  const pendingTotal = (totals?.pendingExpenses ?? 0) + (totals?.openInvoices ?? 0)
  const netBalance = totals?.netBalance ?? 0
  const afterPending = totals?.balanceAfterPending ?? 0
  const workHours = summary?.workWeek?.hours ?? 0
  const workGoal = 44
  const workPercent = Math.min(100, Math.round((workHours / workGoal) * 100))
  const riskPercent = Math.min(86, Math.max(16, Math.round((pendingTotal / Math.max(totals?.income ?? 1, 1)) * 100)))
  const riskLabel = afterPending < 0 ? 'Alto' : pendingTotal > Math.max(netBalance, 1) ? 'Medio' : 'Baixo'

  const drafts = [
    'Qual meu saldo projetado?',
    'Posso comprar um BYD King?',
    'Onde estou gastando mais?',
    'Hoje ganhei R$ 250',
    'Paguei R$ 300 da fatura',
  ]

  const railItems = useMemo(
    () => [
      { id: 'daily' as const, label: 'Painel diario', icon: <Grid2X2 size={18} />, ref: dailyRef },
      { id: 'invoices' as const, label: 'Faturas', icon: <CreditCard size={18} />, ref: invoiceRef },
      { id: 'pending' as const, label: 'Pendencias', icon: <ReceiptText size={18} />, ref: pendingRef },
      { id: 'recent' as const, label: 'Lancamentos', icon: <ListChecks size={18} />, ref: recentRef },
      { id: 'chat' as const, label: 'Bloco financeiro', icon: <MessageCircle size={18} />, ref: chatRef },
    ],
    [],
  )

  const selectRail = (section: RailSection, target: RefObject<HTMLElement | null>) => {
    setActiveSection(section)
    window.requestAnimationFrame(() => target.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }

  const useDraft = (draft: string) => {
    setQuestion(draft)
    window.setTimeout(() => inputRef.current?.focus(), 0)
  }

  const ask = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const text = question.trim()
    if (!text || busy) return

    setQuestion('')
    setBusy(true)
    setError('')
    setMessages((current) => [...current, { author: 'Voce', text }])
    try {
      const reply = await askAgent(text)
      setMessages((current) => [...current, { author: 'Finance OS', text: reply.answer }])
      await loadSummary()
    } catch (err) {
      setMessages((current) => [
        ...current,
        { author: 'Finance OS', text: err instanceof Error ? `Erro: ${err.message}` : 'Erro ao salvar.' },
      ])
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="soft-shell">
      <aside className="soft-sidebar">
        <div className="brand-card">
          <span className="brand-mark">FO</span>
          <div>
            <strong>Finance OS</strong>
            <small>Controle pessoal</small>
          </div>
        </div>

        <nav className="side-nav" aria-label="Secoes">
          {railItems.map((item) => (
            <button
              type="button"
              className={activeSection === item.id ? 'active' : ''}
              onClick={() => selectRail(item.id, item.ref)}
              aria-current={activeSection === item.id ? 'page' : undefined}
              key={item.id}
            >
              {item.icon}
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="profile-card">
          <span>FO</span>
          <div>
            <strong>Lukas Andrade</strong>
            <small>lukas@email.com</small>
          </div>
          <ChevronDown size={18} />
        </div>

        <div className="sync-card">
          <div>
            <strong>{loading ? 'Sincronizando' : 'Sincronizado'}</strong>
            <small>{loading ? 'Agora' : 'Ha 2 min'}</small>
          </div>
          {loading ? <Loader2 className="spin" size={20} /> : <CheckCircle2 size={22} />}
        </div>
      </aside>

      <section className="soft-workspace">
        <header className="soft-topbar" ref={dailyRef}>
          <div className="greeting">
            <span className="sun-chip">
              <Sun size={26} />
            </span>
            <div>
              <h1>Bom dia, Lukas Andrade.</h1>
              <p>Aqui esta o resumo da sua vida financeira.</p>
            </div>
          </div>
          <div className="top-tools">
            <button type="button" className="month-pill">
              {formatMonth(summary?.month)}
              <Calendar size={17} />
            </button>
            <button type="button" className="round-button" aria-label="Notificacoes">
              <Bell size={19} />
              <i />
            </button>
          </div>
        </header>

        {error && <div className="status-note">{error}</div>}

        <section className="top-card-grid">
          <BalanceCard balance={afterPending} />
          <RiskCard percent={riskPercent} label={riskLabel} />
          <WorkCard hours={workHours} goal={workGoal} percent={workPercent} />
          <AlertCard pendingTotal={pendingTotal} afterPending={afterPending} workPercent={workPercent} />
        </section>

        <section className="middle-card-grid">
          <InvoicePanel invoices={summary?.openInvoices ?? []} sectionRef={invoiceRef} focused={activeSection === 'invoices'} />
          <PendingPanel entries={summary?.pendingEntries ?? []} sectionRef={pendingRef} focused={activeSection === 'pending'} />
          <RecentPanel entries={summary?.recentEntries ?? []} sectionRef={recentRef} focused={activeSection === 'recent'} />
        </section>

        <ChatPanel
          sectionRef={chatRef}
          focused={activeSection === 'chat'}
          messages={messages}
          question={question}
          setQuestion={setQuestion}
          busy={busy}
          inputRef={inputRef}
          ask={ask}
          drafts={drafts}
          useDraft={useDraft}
        />
      </section>
    </main>
  )
}

function BalanceCard({ balance }: { balance: number }) {
  return (
    <article className="soft-card balance-card">
      <CardHeader title="Saldo apos pendencias" icon={<Eye size={18} />} />
      <strong className={balance < 0 ? 'danger-text' : 'success-text'}>{money(balance)}</strong>
      <span>Disponivel para uso</span>
      <p className={balance < 0 ? 'danger-text' : 'success-text'}>▲ 8,3% vs. mes anterior</p>
      <svg className="line-graph" viewBox="0 0 240 82" aria-hidden="true">
        <path d="M4 62 C22 58 22 42 43 48 C62 54 65 23 86 28 C109 34 103 66 127 54 C149 43 146 22 168 27 C189 31 187 7 206 18 C222 27 224 42 238 36" />
      </svg>
    </article>
  )
}

function RiskCard({ percent, label }: { percent: number; label: string }) {
  return (
    <article className="soft-card risk-card">
      <CardHeader title="Risco de caixa" icon={<ShieldCheck size={18} />} />
      <div className="gauge" style={{ '--risk': `${percent}%` } as CSSProperties}>
        <strong>{percent}%</strong>
        <span>{label}</span>
      </div>
      <p>Sua saude financeira esta estavel.</p>
    </article>
  )
}

function WorkCard({ hours, goal, percent }: { hours: number; goal: number; percent: number }) {
  return (
    <article className="soft-card work-card">
      <CardHeader title="Horas da semana" icon={<Clock3 size={18} />} />
      <strong>{formatWorkHours(hours)}</strong>
      <span>Meta: {goal}h</span>
      <div className="soft-progress">
        <i style={{ width: `${percent}%` }} />
      </div>
      <div className="split-line">
        <span>Trabalhadas</span>
        <b>{percent}%</b>
      </div>
    </article>
  )
}

function AlertCard({
  pendingTotal,
  afterPending,
  workPercent,
}: {
  pendingTotal: number
  afterPending: number
  workPercent: number
}) {
  const alerts = [
    {
      tone: 'red',
      title: pendingTotal > 0 ? 'Compromissos futuros altos' : 'Sem compromissos altos',
      text: pendingTotal > 0 ? `Voce possui ${money(pendingTotal)} em aberto.` : 'Nenhuma pendencia pesada agora.',
    },
    {
      tone: 'amber',
      title: afterPending < 0 ? 'Saldo apos pendencias negativo' : 'Gasto sob controle',
      text: afterPending < 0 ? 'Evite assumir novas parcelas ate regularizar.' : 'Seu saldo ainda suporta as pendencias.',
    },
    {
      tone: 'green',
      title: workPercent >= 80 ? 'Meta em dia' : 'Horas em andamento',
      text: workPercent >= 80 ? 'Voce esta no caminho certo esta semana.' : 'Ainda faltam horas para bater sua meta.',
    },
  ]

  return (
    <article className="soft-card alert-card">
      <CardHeader title="Alertas" icon={<Bell size={18} />} />
      <div className="alert-list">
        {alerts.map((alert) => (
          <div className="alert-item" data-tone={alert.tone} key={alert.title}>
            <i>!</i>
            <div>
              <strong>{alert.title}</strong>
              <span>{alert.text}</span>
            </div>
          </div>
        ))}
      </div>
      <button type="button" className="ghost-action">Ver todos os alertas <span>→</span></button>
    </article>
  )
}

function InvoicePanel({
  invoices,
  sectionRef,
  focused,
}: {
  invoices: SimpleInvoice[]
  sectionRef: RefObject<HTMLElement | null>
  focused: boolean
}) {
  const invoice = invoices[0]
  const ratio = invoice?.total_amount ? Math.min(100, (invoice.paid_amount / invoice.total_amount) * 100) : 0

  return (
    <section className={`soft-card invoice-card ${focused ? 'focused-card' : ''}`} ref={sectionRef}>
      <CardHeader title="Fatura aberta" icon={<MoreHorizontal size={18} />} />
      {invoice ? (
        <>
          <div className="invoice-box">
            <span className="mini-icon"><CreditCard size={20} /></span>
            <div>
              <strong>{invoice.name}</strong>
              <small>Cartao de credito</small>
            </div>
            <div className="invoice-date">
              <span>Vencimento</span>
              <b>{invoice.due_date ? formatDate(invoice.due_date) : 'Sem data'}</b>
            </div>
          </div>
          <div className="invoice-money">
            <span><small>Valor total</small><b className="danger-text">{money(invoice.total_amount)}</b></span>
            <span><small>Pago</small><b className="success-text">{money(invoice.paid_amount)}</b></span>
            <span><small>Restante</small><b>{money(invoice.remaining_amount)}</b></span>
          </div>
          <div className="soft-progress"><i style={{ width: `${ratio}%` }} /></div>
        </>
      ) : (
        <EmptyState text="Nenhuma fatura aberta." />
      )}
      <button type="button" className="ghost-action">Ver faturas <span>→</span></button>
    </section>
  )
}

function PendingPanel({
  entries,
  sectionRef,
  focused,
}: {
  entries: SimpleEntry[]
  sectionRef: RefObject<HTMLElement | null>
  focused: boolean
}) {
  return (
    <section className={`soft-card pending-card ${focused ? 'focused-card' : ''}`} ref={sectionRef}>
      <CardHeader title="Pendencias" icon={<MoreHorizontal size={18} />} />
      <div className="compact-list">
        {entries.slice(0, 3).map((entry, index) => (
          <article key={entry.id}>
            <span className="mini-icon" data-kind={index % 3}><FileClock size={17} /></span>
            <div>
              <strong>{entry.description}</strong>
              <small>Venc. {formatDate(entry.date)}</small>
            </div>
            <b className="danger-text">{money(entry.amount)}</b>
          </article>
        ))}
        {!entries.length && <EmptyState text="Nenhuma pendencia." />}
      </div>
      <button type="button" className="ghost-action">Ver pendencias <span>→</span></button>
    </section>
  )
}

function RecentPanel({
  entries,
  sectionRef,
  focused,
}: {
  entries: SimpleEntry[]
  sectionRef: RefObject<HTMLElement | null>
  focused: boolean
}) {
  return (
    <section className={`soft-card recent-card ${focused ? 'focused-card' : ''}`} ref={sectionRef}>
      <CardHeader title="Ultimos lancamentos" icon={<MoreHorizontal size={18} />} />
      <div className="compact-list">
        {entries.slice(0, 4).map((entry) => (
          <article key={`${entry.kind}-${entry.id}-${entry.created_at ?? entry.date}`}>
            <span className="mini-icon" data-kind={entry.kind === 'receita' ? 0 : 1}>
              {entry.kind === 'receita' ? <Wallet size={17} /> : <Zap size={17} />}
            </span>
            <div>
              <strong>{entry.description}</strong>
              <small>{formatDate(entry.date)} · {entry.status}</small>
            </div>
            <b className={entry.kind === 'receita' ? 'success-text' : 'danger-text'}>
              {entry.kind === 'receita' ? '+' : '-'} {money(entry.amount)}
            </b>
          </article>
        ))}
        {!entries.length && <EmptyState text="Nenhum lancamento ainda." />}
      </div>
      <button type="button" className="ghost-action">Ver lancamentos <span>→</span></button>
    </section>
  )
}

function ChatPanel({
  sectionRef,
  focused,
  messages,
  question,
  setQuestion,
  busy,
  inputRef,
  ask,
  drafts,
  useDraft,
}: {
  sectionRef: RefObject<HTMLElement | null>
  focused: boolean
  messages: ChatMessage[]
  question: string
  setQuestion: (value: string) => void
  busy: boolean
  inputRef: RefObject<HTMLInputElement | null>
  ask: (event: FormEvent<HTMLFormElement>) => void
  drafts: string[]
  useDraft: (draft: string) => void
}) {
  return (
    <section className={`soft-card chat-dock ${focused ? 'focused-card' : ''}`} ref={sectionRef}>
      <div className="chat-heading">
        <div>
          <h2>Bloco financeiro</h2>
          <p>Seu assistente inteligente para decisoes financeiras melhores.</p>
        </div>
        <div className="quick-drafts">
          {drafts.slice(0, 3).map((draft) => (
            <button type="button" onClick={() => useDraft(draft)} key={draft}>
              {draft}
            </button>
          ))}
        </div>
      </div>

      <div className="chat-preview">
        {messages.slice(-2).map((message, index) => (
          <article className={message.author === 'Voce' ? 'from-user' : ''} key={`${message.text}-${index}`}>
            <small>{message.author}</small>
            <p>{message.text}</p>
          </article>
        ))}
      </div>

      <form className="soft-input" onSubmit={ask}>
        <input
          ref={inputRef}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Pergunte ao Finance OS..."
          disabled={busy}
        />
        <button type="submit" disabled={busy || !question.trim()} aria-label="Enviar">
          {busy ? <Loader2 className="spin" size={18} /> : <Send size={18} />}
        </button>
      </form>
    </section>
  )
}

function CardHeader({ title, icon }: { title: string; icon: ReactNode }) {
  return (
    <div className="card-header">
      <h2>{title}</h2>
      <span>{icon}</span>
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="empty-state">
      <CheckCircle2 size={18} />
      <span>{text}</span>
    </div>
  )
}

export default App
