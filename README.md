# Finance Decision OS

Software local para finanças pessoais com dashboard decisório, importação CSV, SQLite e agente IA.

## Rodar

Backend:

```powershell
cd backend
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

Abra `http://localhost:5173`.

## CSV aceito

Cabeçalhos flexíveis: `date/data`, `description/descrição/memo`, `amount/valor`, `category/categoria`, `account/conta`.

## IA

Sem `OPENAI_API_KEY`, agente local usa regras, métricas e cenários. Com `OPENAI_API_KEY`, usa provedor OpenAI e mantém fallback local.
 
## Backend v0.2

Endpoints principais:

- `GET /api/dashboard` - KPIs, serie mensal, categorias, orcamentos, recorrencias, metas, insights e plano de acao.
- `GET /api/transactions` - filtros por `start`, `end`, `category`, `account`, `search`, `limit`.
- `POST /api/import` - importa CSV com deduplicacao por fingerprint.
- `GET /api/budgets` e `POST /api/budgets` - limites mensais por categoria.
- `GET /api/goals`, `POST /api/goals`, `PATCH /api/goals/{id}`, `DELETE /api/goals/{id}` - metas financeiras.
- `POST /api/scenario` - simula compra e impacto em poupanca/orcamento.
- `POST /api/agent/chat` - agente decisorio local ou OpenAI.

Testes:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

## Deploy gratis recomendado

Arquitetura:

- Banco: Supabase Free Postgres.
- Backend: Render Free.
- Frontend: Cloudflare Pages Free.

### 1. Supabase

Crie um projeto no Supabase e copie a connection string Postgres.

Use formato parecido:

```text
postgresql://postgres.xxxxx:SENHA@aws-...supabase.com:6543/postgres?sslmode=require
```

### 2. Render backend

Crie Web Service pelo GitHub usando este repo.

Config:

```text
Root Directory: backend
Build Command: pip install -r requirements.txt
Start Command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
Plan: Free
```

Variaveis:

```text
DATABASE_URL=sua_url_do_supabase
APP_USER=lukas
APP_PASSWORD=sua_senha_forte
ALLOWED_ORIGINS=*
OPENAI_API_KEY=opcional
```

### 3. Cloudflare Pages frontend

Crie Pages pelo GitHub.

Config:

```text
Root directory: frontend
Build command: npm run build
Build output directory: dist
```

Variavel:

```text
VITE_API_URL=https://seu-backend.onrender.com
```

Depois do deploy, abra a URL do Cloudflare. Login: `APP_USER` + `APP_PASSWORD`.
