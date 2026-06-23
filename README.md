# Transcript Intelligence Platform

An AI-powered enterprise call transcript analysis system built for AegisCloud's B2B SaaS operations.

## What It Does

Transforms 100 raw enterprise call transcripts into actionable intelligence for Product, Sales, Support, and Engineering leadership — automatically.

**Pipeline output from 100 transcripts:**
- 100 calls classified by type (42 external, 30 support, 28 internal)
- 100 topics discovered and labeled
- 26 high-risk customers identified with evidence citations
- 56 calls flagged for human review with audit trail
- 73% frustration detection rate across customer calls

## Architecture

```
Raw JSON Transcripts (100 folders)
        ↓
Ingestion Agent       ← Rule-based call type inference, no LLM
        ↓
Topic Discovery Agent ← GPT-4o-mini, constrained to 12 categories
        ↓
Sentiment Agent       ← Hybrid: math for score/arc, LLM for frustration
        ↓
Churn Risk Agent      ← Hybrid: keyword scan + LLM for citations
        ↓
Synthesis Agent       ← GPT-4o-mini, combines all outputs
        ↓
SQLite + FastAPI       ← REST API serving the frontend
        ↓
Next.js Dashboard     ← 5-page SaaS UI
```

## Multi-Agent Design (LangGraph)

Each agent is a node in a directed graph. Data flows as `ProcessedTranscript` objects — typed Pydantic models that enforce contracts between agents.

| Agent | Approach | Why |
|---|---|---|
| Ingestion | Rule-based | Deterministic, free, 100% accurate |
| Topic | LLM (constrained) | Human-readable labels, works on 1-100 transcripts |
| Sentiment | Hybrid | Math for score, LLM only for nuanced signals |
| Risk | Hybrid | Keywords for detection, LLM for severity + citations |
| Synthesis | LLM | Narrative requires language understanding |

## AI Governance

Every AI decision produces:
- **Confidence score** (0.0–1.0) on topic classifications
- **Citations** — exact transcript sentences as evidence for risk flags
- **Audit logs** — every agent action logged with timestamp and outcome
- **Human review flags** — 56/100 calls flagged with specific reasons
- **Reasoning field** — LLM explains why it made each classification

## Tech Stack

| Layer | Technology | Decision |
|---|---|---|
| Backend | FastAPI + Python | Async, auto-docs, Pydantic integration |
| AI Agents | LangGraph + OpenAI GPT-4o-mini | Structured orchestration, cost-efficient |
| Database | SQLite | Right tool for scale; swappable to Postgres |
| Frontend | Next.js 15 + TypeScript + Tailwind | Production-grade, type-safe |
| Dependency Mgmt | uv | Modern Python tooling, 10x faster than pip |

## Running Locally

### Prerequisites
- Python 3.11+
- Node 20+
- OpenAI API key

### Backend
```bash
cd transcript-intelligence
uv venv
.venv\Scripts\activate        # Windows
uv add -r requirements.txt   # or: uv sync
cp .env.example .env          # add your OPENAI_API_KEY
uvicorn backend.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`


## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/dashboard` | Aggregated stats for dashboard |
| `GET /api/transcripts` | All transcripts with analysis |
| `GET /api/risk/high` | High-risk calls with citations |
| `GET /api/sentiment/escalations` | Escalation-flagged calls |
| `GET /api/review/pending` | Human review queue |
| `POST /api/chat` | RAG-powered chat |
| `GET /docs` | Auto-generated API documentation |

## Key Engineering Decisions

**Why hybrid agents instead of pure LLM?**
Using LLM only where needed (frustration detection, risk narrative) and math/rules everywhere else keeps costs at ~$0.50 for 100 transcripts while maintaining explainability.

**Why citations in risk analysis?**
For a security company, "your AI flagged this customer as high risk" must be backed by specific evidence. Citations provide the exact transcript sentences that triggered a flag — auditable, verifiable, trustworthy.

**Why SQLite?**
100 transcripts doesn't need a Postgres container. The repository pattern in `database.py` means swapping to Postgres is a 5-line change when scale requires it.

## Project Structure

```
transcript-intelligence/
├── backend/
│   ├── agents/
│   │   ├── ingestion.py      # Reads + classifies transcripts
│   │   ├── topic.py          # LLM topic classification
│   │   ├── sentiment.py      # Hybrid sentiment analysis
│   │   ├── risk.py           # Churn risk scoring
│   │   └── synthesis.py      # Executive summary generation
│   ├── main.py               # FastAPI application
│   ├── database.py           # SQLite repository layer
│   ├── models.py             # Pydantic data contracts
│   ├── retrieval.py          # ChromaDB vector store + RAG
│   └── pipeline.py           # LangGraph orchestration
├── frontend/
│   └── app/                  # Next.js pages
├── dataset/                  # 100 transcript folders
├── BONUS_INSIGHTS.md
└── README.md
```
