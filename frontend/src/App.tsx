import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import {
  ArrowDownRight,
  ArrowUpRight,
  CheckCircle2,
  CreditCard,
  FileClock,
  Landmark,
  ListChecks,
  Loader2,
  MessageCircle,
  RefreshCw,
  Send,
  Wallet,
} from 'lucide-react'
import { askAgent, getSimpleSummary } from './api'
import type { SimpleEntry, SimpleInvoice, SimpleSummary } from './types'
import './App.css'

type ChatMessage = {
  author: 'Finance OS' | 'Voce'
  text: string
}

type MetricTone = 'income' | 'expense' | 'pending'

type MetricItem = {
  label: string
  value: string
  detail: string
  icon: ReactNode
  tone: MetricTone
}

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
  if (!value) return 'mês atual'
  const [year, month] = value.split('-').map(Number)
  return new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric' }).format(new Date(year, month - 1, 1))
}

function App() {
  const [summary, setSummary] = useState<SimpleSummary | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>(starterMessages)
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const loadSummary = async () => {
    setError('')
    setLoading(true)
    try {
      const data = await getSimpleSummary()
      setSummary(data)
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
  const totalPending = (totals?.pendingExpenses ?? 0) + (totals?.openInvoices ?? 0)

  const metrics = useMemo<MetricItem[]>(
    () => [
      {
        label: 'Entradas do mês',
        value: money(totals?.income),
        detail: 'receitas pagas',
        icon: <ArrowUpRight size={18} />,
        tone: 'income',
      },
      {
        label: 'Saídas pagas',
        value: money(totals?.paidExpenses),
        detail: 'já saiu do caixa',
        icon: <ArrowDownRight size={18} />,
        tone: 'expense',
      },
      {
        label: 'Contas pendentes',
        value: money(totals?.pendingExpenses),
        detail: `${summary?.pendingEntries.length ?? 0} em aberto`,
        icon: <FileClock size={18} />,
        tone: 'pending',
      },
      {
        label: 'Faturas abertas',
        value: money(totals?.openInvoices),
        detail: `${summary?.openInvoices.length ?? 0} fatura(s)`,
        icon: <CreditCard size={18} />,
        tone: 'pending',
      },
    ],
    [summary, totals],
  )

  const drafts = [
    'Hoje ganhei R$ 250',
    'Gastei R$ 40 no mercado',
    'Tenho R$ 120 de internet para pagar',
    'Tenho R$ 1.081,38 de fatura, R$ 481 é da parcela do meu celular, o resto são compras avulsas',
    'Paguei R$ 300 da fatura',
    'Paguei a internet',
  ]

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

  const useDraft = (draft: string) => {
    setQuestion(draft)
    window.setTimeout(() => inputRef.current?.focus(), 0)
  }

  return (
    <main className="executive-shell">
      <aside className="exec-rail" aria-label="Resumo lateral">
        <div className="brand-block">
          <span>FO</span>
          <div>
            <strong>Finance OS</strong>
            <small>Controle pessoal</small>
          </div>
        </div>

        <div className="rail-menu" aria-label="Seções">
          <span className="active">Painel diário</span>
          <span>Faturas</span>
          <span>Pendências</span>
          <span>Lançamentos</span>
        </div>

        <div className="rail-balance">
          <small>após pendências</small>
          <strong className={(totals?.balanceAfterPending ?? 0) < 0 ? 'expense-text' : 'income-text'}>
            {money(totals?.balanceAfterPending)}
          </strong>
          <span>{summary?.openInvoices.length ?? 0} fatura(s) abertas</span>
        </div>
      </aside>

      <section className="exec-workspace">
        <header className="exec-topbar">
          <div>
            <span>{formatMonth(summary?.month)}</span>
            <h1>Controle financeiro diário</h1>
          </div>
          <div className="top-actions">
            <span className="sync-pill">{loading ? 'sincronizando' : 'online'}</span>
            <button type="button" onClick={() => void loadSummary()} disabled={loading}>
              {loading ? <Loader2 size={17} className="spin" /> : <RefreshCw size={17} />}
              Atualizar
            </button>
          </div>
        </header>

        {error && <div className="status-line danger">{error}</div>}

        <section className="executive-overview" aria-label="Resumo executivo">
          <article className="primary-balance">
            <div>
              <span>saldo líquido</span>
              <strong className={(totals?.netBalance ?? 0) < 0 ? 'expense-text' : ''}>
                {money(totals?.netBalance)}
              </strong>
              <p>Entradas menos saídas já pagas neste mês.</p>
            </div>
            <Wallet size={28} />
          </article>

          <article className="pending-impact">
            <div>
              <span>impacto em aberto</span>
              <strong>{money(totalPending)}</strong>
              <p>Pendências e faturas que ainda faltam pagar.</p>
            </div>
            <Landmark size={28} />
          </article>

          <div className="metric-grid" aria-label="Indicadores principais">
            {metrics.map((item) => (
              <MetricTile item={item} key={item.label} />
            ))}
          </div>
        </section>

        <section className="exec-grid">
          <section className="chat-panel">
            <div className="section-title">
              <div>
                <span>entrada rápida</span>
                <h2>Bloco financeiro</h2>
              </div>
              <MessageCircle size={19} />
            </div>

            <div className="chat-feed" aria-live="polite">
              {messages.slice(-8).map((message, index) => (
                <article className={message.author === 'Voce' ? 'from-user' : ''} key={`${message.author}-${index}-${message.text}`}>
                  <span>{message.author}</span>
                  <p>{message.text}</p>
                </article>
              ))}
            </div>

            <form className="chat-form" onSubmit={ask}>
              <input
                ref={inputRef}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="Ex.: paguei R$ 300 da fatura"
                disabled={busy}
              />
              <button type="submit" disabled={busy || !question.trim()} aria-label="Enviar">
                {busy ? <Loader2 size={18} className="spin" /> : <Send size={18} />}
              </button>
            </form>

            <div className="drafts" aria-label="Exemplos de comando">
              {drafts.map((draft) => (
                <button type="button" key={draft} onClick={() => useDraft(draft)}>
                  {draft}
                </button>
              ))}
            </div>
          </section>

          <section className="summary-panel">
            <div className="section-title">
              <div>
                <span>fechamento</span>
                <h2>Posição atual</h2>
              </div>
              <Wallet size={19} />
            </div>
            <div className="closing-number">
              <small>saldo líquido</small>
              <strong className={(totals?.netBalance ?? 0) < 0 ? 'expense-text' : ''}>{money(totals?.netBalance)}</strong>
            </div>
            <div className="closing-row">
              <span>Pendências totais</span>
              <b>{money(totalPending)}</b>
            </div>
            <div className="closing-row strong">
              <span>Depois de pagar tudo</span>
              <b className={(totals?.balanceAfterPending ?? 0) < 0 ? 'expense-text' : 'income-text'}>
                {money(totals?.balanceAfterPending)}
              </b>
            </div>
          </section>

          <ListPanel
            title="Contas pendentes"
            eyebrow="a pagar"
            icon={<FileClock size={19} />}
            empty="Nenhuma conta pendente."
            entries={summary?.pendingEntries ?? []}
          />

          <InvoicePanel invoices={summary?.openInvoices ?? []} />

          <ListPanel
            title="Últimos lançamentos"
            eyebrow="histórico"
            icon={<ListChecks size={19} />}
            empty="Nenhum lançamento ainda."
            entries={summary?.recentEntries ?? []}
            recent
          />
        </section>
      </section>
    </main>
  )
}

function MetricTile({ item }: { item: MetricItem }) {
  return (
    <article className={`metric ${item.tone}`}>
      <span>{item.icon}</span>
      <div>
        <small>{item.label}</small>
        <strong>{item.value}</strong>
        <p>{item.detail}</p>
      </div>
    </article>
  )
}

function ListPanel({
  title,
  eyebrow,
  icon,
  empty,
  entries,
  recent = false,
}: {
  title: string
  eyebrow: string
  icon: ReactNode
  empty: string
  entries: SimpleEntry[]
  recent?: boolean
}) {
  return (
    <section className="list-panel">
      <div className="section-title">
        <div>
          <span>{eyebrow}</span>
          <h2>{title}</h2>
        </div>
        {icon}
      </div>
      <div className="entry-list">
        {entries.map((entry) => (
          <article key={`${entry.kind}-${entry.id}-${entry.created_at ?? entry.date}`}>
            <div>
              <strong>{entry.description}</strong>
              <span>{formatDate(entry.date)} · {entry.kind} · {entry.status}</span>
            </div>
            <b className={entry.kind === 'receita' ? 'income-text' : entry.kind === 'fatura' ? '' : 'expense-text'}>
              {entry.kind === 'receita' ? '+' : recent && entry.kind === 'fatura' ? '' : '-'}{money(entry.amount)}
            </b>
          </article>
        ))}
        {!entries.length && (
          <article className="empty">
            <CheckCircle2 size={18} />
            <span>{empty}</span>
          </article>
        )}
      </div>
    </section>
  )
}

function InvoicePanel({ invoices }: { invoices: SimpleInvoice[] }) {
  return (
    <section className="list-panel invoice-panel">
      <div className="section-title">
        <div>
          <span>cartão</span>
          <h2>Faturas abertas</h2>
        </div>
        <CreditCard size={19} />
      </div>
      <div className="invoice-list">
        {invoices.map((invoice) => {
          const ratio = invoice.total_amount ? Math.min(100, (invoice.paid_amount / invoice.total_amount) * 100) : 0
          return (
            <article key={invoice.id}>
              <div className="invoice-head">
                <div>
                  <strong>{invoice.name}</strong>
                  <span>{invoice.status} · pago {money(invoice.paid_amount)}</span>
                </div>
                <b>{money(invoice.remaining_amount)}</b>
              </div>
              <div className="progress">
                <i style={{ width: `${ratio}%` }} />
              </div>
              <div className="invoice-items">
                {invoice.items.map((item) => (
                  <span key={item.id}>
                    {item.description}
                    <b>{money(item.amount)}</b>
                  </span>
                ))}
              </div>
            </article>
          )
        })}
        {!invoices.length && (
          <article className="empty">
            <CheckCircle2 size={18} />
            <span>Nenhuma fatura aberta.</span>
          </article>
        )}
      </div>
    </section>
  )
}

export default App
