# ResearchMate MVP

A local literature management & AI-assisted writing tool for researchers. Single-user, local deployment.

## Features

- **Library**: Upload PDFs, auto-parse via GROBID, vectorize into 4 dimensions (background / method / result / conclusion).
- **Smart Reader**: PDF rendering, highlight/notes, selection toolbar (translate / explain / highlight), per-paper AI Q&A and summaries.
- **Writing Wizard**: 6-step guided authoring (topic → outline → materials → draft → abstract → export) with RAG material recommendations from your library, exporting to Word (.docx).
- **General Chat**: Conversational assistant with optional library-RAG and web-search toggles.

## Architecture

```
ResearchMate/
├── backend/        FastAPI + SQLAlchemy + pgvector
├── frontend/       React + Vite + TypeScript + Ant Design
└── docker-compose.yml   PostgreSQL (pgvector) + GROBID
```

## Prerequisites

- Python 3.11+
- Node.js 18+
- Docker & Docker Compose (for PostgreSQL+pgvector and GROBID)
- An OpenAI-compatible LLM API key (and embedding endpoint)

## Setup

### 1. Start infrastructure

```bash
docker compose up -d
```

This launches:
- PostgreSQL 15 with pgvector at `localhost:5432` (user/db: `researchmate`).
- GROBID at `http://localhost:8070`.

### 2. Configure the backend

```bash
cd backend
cp .env.example .env
# edit .env: set LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, EMBEDDING_MODEL
```

Install and run:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

On first start the backend automatically enables the `vector` extension and creates all tables.

### 3. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Register an account, then upload a PDF.

## Usage flow

1. **Library** → upload a PDF. It enters `processing` then becomes `ready`.
2. **Reader** → click a ready paper. Select text to translate/explain/highlight; use the AI tab to ask questions about the paper; generate a full summary.
3. **Write** → click the Write nav item. Walk through the 6 steps; in step 3 you can pull relevant materials from your library; in step 6 export to Word.
4. **Chat** → general assistant; toggle "Library" to ground answers in your uploaded papers.

## Configuration notes

- Any OpenAI-compatible endpoint works (OpenAI, Azure OpenAI, local vLLM/ollama with an OpenAI shim). Set `LLM_BASE_URL`, `LLM_MODEL`, `EMBEDDING_MODEL` accordingly. The embedding dimension defaults to `1536` (text-embedding-3-small); if you change it, also update `EMBEDDING_DIM` in `.env` and the `Vector(...)` column in the model.
- PDF files are stored under `backend/storage/pdfs/`.
- The GROBID parse + LLM dimension extraction + embedding all run in a FastAPI background task after upload.

## API

Interactive docs at http://localhost:8000/docs once the backend is running. All routes are prefixed with `/api/v1` and require a JWT bearer token except `/auth/register` and `/auth/login`.
