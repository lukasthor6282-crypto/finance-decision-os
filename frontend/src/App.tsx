import {
  Bell,
  Bot,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  CircleDollarSign,
  Clock3,
  Database,
  Home,
  LockKeyhole,
  MessageCircle,
  PieChart,
  Search,
  Send,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  TrendingDown,
  TrendingUp,
  WalletCards,
} from 'lucide-react'
import './App.css'

const navItems = [
  { label: 'Hoje', icon: <Home size={19} />, active: true },
  { label: 'Fluxo', icon: <TrendingUp size={19} /> },
  { label: 'Categorias', icon: <PieChart size={19} /> },
  { label: 'Dados', icon: <Database size={19} /> },
]

const messages = [
  {
    author: 'Finance OS',
    text: 'Atualizei seu caixa com os lançamentos locais. Julho fecha positivo se o mercado ficar abaixo de R$ 1.120.',
  },
  {
    author: 'Você',
    text: 'Qual decisão devo revisar hoje?',
  },
  {
    author: 'Finance OS',
    text: 'Assinaturas. Três cobranças subiram juntas e somam R$ 246/mês. Cortar uma mantém sua meta de reserva sem mexer em lazer.',
  },
]

const decisions = [
  { title: 'Assinaturas', detail: '3 altas detectadas', state: 'revisar' },
  { title: 'Mercado', detail: 'R$ 420 livres até dia 31', state: 'ok' },
  { title: 'Compra grande', detail: 'adiar reduz risco semanal', state: 'avaliar' },
]

const cards = [
  { label: 'Saldo atual', value: 'R$ 29.568,31', hint: 'após lançamentos locais', icon: <CircleDollarSign /> },
  { label: 'Queima diária', value: 'R$ 307,72', hint: 'média dos últimos 18 dias', icon: <TrendingDown /> },
  { label: 'Reserva', value: '37,5%', hint: 'meta em progresso', icon: <CheckCircle2 /> },
]

const riskRows = [
  { name: 'Hoje', value: 'baixo', width: '28%' },
  { name: '7 dias', value: 'baixo', width: '36%' },
  { name: '30 dias', value: 'controlado', width: '52%' },
]

function App() {
  return (
    <div className="os-shell">
      <aside className="side-rail glass-sheet" aria-label="Navegação">
        <a className="app-mark" href="#inicio" aria-label="Finance OS">
          <WalletCards size={20} />
        </a>
        <nav>
          {navItems.map((item) => (
            <button className={item.active ? 'active' : ''} type="button" key={item.label} aria-label={item.label}>
              {item.icon}
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <button className="rail-button" type="button" aria-label="Alertas">
          <Bell size={19} />
        </button>
      </aside>

      <section className="workspace" id="inicio">
        <header className="workspace-top glass-sheet">
          <div>
            <span>Quinta, 02 Jul</span>
            <strong>Finance OS</strong>
          </div>
          <div className="top-tools">
            <button type="button"><CalendarDays size={16} /> Julho <ChevronDown size={15} /></button>
            <button type="button"><LockKeyhole size={16} /> Local</button>
          </div>
        </header>

        <main className="personal-grid">
          <section className="assistant-pane glass-panel" aria-label="Agente financeiro pessoal">
            <div className="assistant-head">
              <span className="agent-avatar"><Bot size={22} /></span>
              <div>
                <h1>Bom dia, Lukas.</h1>
                <p>Revisei seu caixa, orçamento e riscos pendentes.</p>
              </div>
            </div>

            <div className="status-row">
              <span><Sparkles size={15} /> 4 sinais novos</span>
              <span><ShieldAlert size={15} /> risco baixo</span>
              <span><Clock3 size={15} /> projeção 30 dias</span>
            </div>

            <div className="chat-window">
              {messages.map((message) => (
                <article className={message.author === 'Você' ? 'message user' : 'message agent'} key={message.text}>
                  <span>{message.author}</span>
                  <p>{message.text}</p>
                </article>
              ))}
            </div>

            <form className="ask-box" onSubmit={(event) => event.preventDefault()}>
              <label htmlFor="ask-agent">Perguntar ao financeiro</label>
              <div>
                <Search size={18} />
                <input id="ask-agent" type="text" placeholder="Ex.: posso comprar isso hoje?" />
                <button type="button" aria-label="Enviar pergunta"><Send size={18} /></button>
              </div>
            </form>
          </section>

          <aside className="right-column">
            <section className="balance-card glass-panel">
              <div className="panel-title">
                <h2>Resumo</h2>
                <button type="button"><SlidersHorizontal size={15} /> Filtro</button>
              </div>
              <strong>R$ 29.568,31</strong>
              <p>saldo atual depois dos dados importados</p>
              <div className="mini-line" aria-label="Fluxo projetado">
                <i />
                <i />
                <i />
                <i />
                <i />
                <i />
              </div>
            </section>

            <section className="decision-card glass-panel">
              <div className="panel-title">
                <h2>Decisões</h2>
                <span>hoje</span>
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
              </div>
            </section>
          </aside>

          <section className="glass-panel risk-panel">
            <div className="panel-title">
              <h2>Risco de caixa</h2>
              <span>controlado</span>
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
              <h2>Notas locais</h2>
              <MessageCircle size={17} />
            </div>
            <p>
              Próxima revisão sugerida: assinaturas e mercado. Nenhuma ação automática foi feita.
            </p>
          </section>
        </main>
      </section>
    </div>
  )
}

export default App
