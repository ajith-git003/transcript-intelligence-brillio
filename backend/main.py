# backend/main.py
import os
import json
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

from backend.database import (
    init_db,
    get_dashboard_stats,
    get_all_transcripts,
    get_transcript_by_id,
    get_audit_logs,
    get_connection
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Starting Transcript Intelligence API...")
    init_db()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM transcripts")
    count = cursor.fetchone()["count"]
    conn.close()

    if count == 0:
        print("📂 No data found — running pipeline...")
        dataset_path = os.getenv(
            "DATASET_PATH",
            r"D:\Downloads\interview-assignment\interview-assignment\dataset"
        )
        from backend.agents.ingestion import ingest_all_transcripts
        from backend.agents.topic import analyze_topics_batch
        from backend.agents.sentiment import analyze_sentiments_batch
        from backend.agents.risk import analyze_risks_batch
        from backend.agents.synthesis import synthesize_batch

        transcripts = ingest_all_transcripts(dataset_path)
        topics = analyze_topics_batch(transcripts)
        sentiments = analyze_sentiments_batch(transcripts)
        risks = analyze_risks_batch(transcripts)
        synthesize_batch(transcripts, topics, sentiments, risks)
        print("✅ Pipeline complete")

        # Build vector index after pipeline
        print("🔢 Building vector search index...")
        from backend.retrieval import index_transcripts
        index_transcripts()
    else:
        print(f"✅ Found {count} transcripts in database — skipping pipeline")
        # Build vector index if not already built
        from backend.retrieval import index_transcripts
        index_transcripts()

    yield
    print("👋 Shutting down...")


app = FastAPI(
    title="Transcript Intelligence API",
    description="AI-powered enterprise call transcript analysis platform",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "transcript-intelligence"}


@app.get("/api/dashboard")
def get_dashboard():
    return get_dashboard_stats()


@app.get("/api/dashboard/topic-distribution")
def get_topic_distribution():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT primary_topic, COUNT(*) as count
        FROM topic_analyses
        GROUP BY primary_topic
        ORDER BY count DESC
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"topics": rows}


@app.get("/api/dashboard/sentiment-by-type")
def get_sentiment_by_call_type():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            t.call_type,
            sa.overall_sentiment,
            COUNT(*) as count,
            AVG(sa.sentiment_score) as avg_score
        FROM transcripts t
        JOIN sentiment_analyses sa ON t.meeting_id = sa.meeting_id
        GROUP BY t.call_type, sa.overall_sentiment
        ORDER BY t.call_type, sa.overall_sentiment
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"sentiment_by_type": rows}


@app.get("/api/transcripts")
def list_transcripts(
    call_type: str = Query(None),
    risk_level: str = Query(None),
    limit: int = Query(50),
    offset: int = Query(0)
):
    conn = get_connection()
    cursor = conn.cursor()

    where_clauses = []
    params = []

    if call_type:
        where_clauses.append("t.call_type = ?")
        params.append(call_type)
    if risk_level:
        where_clauses.append("ra.risk_level = ?")
        params.append(risk_level)

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    cursor.execute(f"""
        SELECT 
            t.meeting_id, t.title, t.call_type, t.start_time,
            t.duration_minutes, t.organizer_email,
            t.total_sentences, t.positive_count, t.negative_count,
            ta.primary_topic, ta.confidence as topic_confidence,
            sa.overall_sentiment, sa.sentiment_score,
            sa.frustration_detected, sa.escalation_risk,
            ra.risk_level, ra.risk_score,
            es.one_line_summary, es.human_review_required
        FROM transcripts t
        LEFT JOIN topic_analyses ta ON t.meeting_id = ta.meeting_id
        LEFT JOIN sentiment_analyses sa ON t.meeting_id = sa.meeting_id
        LEFT JOIN risk_analyses ra ON t.meeting_id = ra.meeting_id
        LEFT JOIN executive_summaries es ON t.meeting_id = es.meeting_id
        {where_sql}
        ORDER BY ra.risk_score DESC
        LIMIT ? OFFSET ?
    """, params + [limit, offset])

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"transcripts": rows, "total": len(rows)}


@app.get("/api/transcripts/{meeting_id}")
def get_transcript(meeting_id: str):
    data = get_transcript_by_id(meeting_id)
    if not data:
        raise HTTPException(status_code=404, detail="Transcript not found")
    for field in ["all_emails", "themes", "keywords", "sentiment_arc",
                  "key_moments", "churn_indicators", "citations",
                  "key_findings", "recommendations"]:
        if data.get(field) and isinstance(data[field], str):
            try:
                data[field] = json.loads(data[field])
            except Exception:
                pass
    return data


@app.get("/api/risk/high")
def get_high_risk():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            t.meeting_id, t.title, t.call_type, t.organizer_email,
            ra.risk_level, ra.risk_score, ra.churn_indicators,
            ra.competitor_mentions, ra.pricing_objections, ra.citations,
            sa.overall_sentiment, sa.frustration_detected,
            es.one_line_summary, es.recommendations
        FROM transcripts t
        JOIN risk_analyses ra ON t.meeting_id = ra.meeting_id
        LEFT JOIN sentiment_analyses sa ON t.meeting_id = sa.meeting_id
        LEFT JOIN executive_summaries es ON t.meeting_id = es.meeting_id
        WHERE ra.risk_level = 'high'
        ORDER BY ra.risk_score DESC
    """)
    rows = []
    for row in cursor.fetchall():
        d = dict(row)
        for field in ["churn_indicators", "competitor_mentions",
                      "citations", "recommendations"]:
            if d.get(field) and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except Exception:
                    pass
        rows.append(d)
    conn.close()
    return {"high_risk": rows, "count": len(rows)}


@app.get("/api/risk/summary")
def get_risk_summary():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT risk_level, COUNT(*) as count, AVG(risk_score) as avg_score
        FROM risk_analyses
        GROUP BY risk_level
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"risk_summary": rows}


@app.get("/api/sentiment/escalations")
def get_escalations():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            t.meeting_id, t.title, t.call_type,
            sa.overall_sentiment, sa.sentiment_score,
            sa.frustration_detected, sa.escalation_risk,
            sa.resolution_detected, sa.key_moments,
            es.one_line_summary
        FROM transcripts t
        JOIN sentiment_analyses sa ON t.meeting_id = sa.meeting_id
        LEFT JOIN executive_summaries es ON t.meeting_id = es.meeting_id
        WHERE sa.escalation_risk = 1
        ORDER BY sa.sentiment_score ASC
    """)
    rows = []
    for row in cursor.fetchall():
        d = dict(row)
        if d.get("key_moments") and isinstance(d["key_moments"], str):
            try:
                d["key_moments"] = json.loads(d["key_moments"])
            except Exception:
                pass
        rows.append(d)
    conn.close()
    return {"escalations": rows, "count": len(rows)}


@app.get("/api/review/pending")
def get_pending_reviews():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            es.meeting_id, es.title, es.call_type,
            es.one_line_summary, es.review_reason,
            es.human_review_required, es.processed_at,
            ra.risk_level, ra.risk_score,
            sa.overall_sentiment
        FROM executive_summaries es
        LEFT JOIN risk_analyses ra ON es.meeting_id = ra.meeting_id
        LEFT JOIN sentiment_analyses sa ON es.meeting_id = sa.meeting_id
        WHERE es.human_review_required = 1
        ORDER BY ra.risk_score DESC
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return {"pending_reviews": rows, "count": len(rows)}


@app.get("/api/audit-logs")
def get_logs(meeting_id: str = Query(None)):
    logs = get_audit_logs(meeting_id)
    return {"logs": logs}


@app.get("/api/search")
def semantic_search_endpoint(
    q: str = Query(..., description="Search query"),
    n: int = Query(5, description="Number of results")
):
    """
    Semantic vector search endpoint.
    Unlike keyword search, this understands meaning.
    'customer losing access' matches 'complete loss of threat visibility'
    """
    from backend.retrieval import semantic_search
    results = semantic_search(q, n_results=n)
    return {"query": q, "results": results, "count": len(results)}


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []


@app.post("/api/chat")
def chat(request: ChatRequest):
    """
    RAG-powered chat using semantic vector search.

    FLOW:
    1. Embed the question using text-embedding-3-small
    2. Find top 5 semantically similar transcripts in ChromaDB
    3. Pass those transcripts as context to GPT-4o-mini
    4. Return answer with source citations

    This is TRUE RAG — retrieval is semantic, not keyword-based.
    'customers at risk' retrieves 'renewal concerns' and
    'competitive evaluation' even without exact word match.
    """
    from backend.retrieval import rag_answer
    result = rag_answer(
        question=request.message,
        conversation_history=request.history,
        n_context_docs=5
    )
    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "source_titles": result["source_titles"]
    }