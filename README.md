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

## Deploy simples

Este projeto agora pode rodar como 1 container:

- FastAPI serve `/api/*`.
- O frontend Vite fica servido pelo mesmo backend.
- SQLite fica em `/data/finance.db`.
- Se `APP_PASSWORD` existir, o app fica protegido por login/senha Basic Auth.

### Railway recomendado

Use para coisa pessoal simples:

1. Envie este projeto para GitHub.
2. No Railway, crie um projeto pelo repo.
3. Ele detecta o `Dockerfile`.
4. Crie um Volume no servico e monte em `/data`.
5. Variaveis:

```text
FINANCE_DB_PATH=/data/finance.db
STATIC_DIR=/app/static
APP_USER=lukas
APP_PASSWORD=uma_senha_forte
OPENAI_API_KEY=opcional
```

### Render alternativo

Use `render.yaml`. Ele ja declara Docker, healthcheck e disk em `/data`.
Defina `APP_PASSWORD` no painel.

### VPS local/barato

Com Docker instalado:

```powershell
$env:APP_PASSWORD="uma_senha_forte"
docker compose up -d --build
```

Abra `http://SEU_IP:8000`.
