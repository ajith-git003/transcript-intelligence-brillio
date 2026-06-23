# backend/database.py
# ============================================================
# DATABASE LAYER — SQLite via Python's built-in sqlite3
# ============================================================
# WHY SQLite and not PostgreSQL?
# For 100 transcripts this is more than enough.
# SQLite = zero setup, zero Docker container, file on disk.
# We can swap to PostgreSQL later by changing ~5 lines.
# This is a conscious engineering tradeoff — right tool for the scale.
#
# WHAT THIS FILE DOES:
# 1. Creates the database + tables on first run
# 2. Provides functions to save agent outputs
# 3. Provides functions to query data for the API
#
# PATTERN USED: Repository pattern
# The rest of the app never writes raw SQL — it calls these functions.
# This means if we switch to PostgreSQL later, only THIS file changes.
# ============================================================

import sqlite3
import json
import os
from datetime import datetime
from typing import Optional
from backend.models import (
    ProcessedTranscript,
    TopicAnalysis,
    SentimentAnalysis,
    RiskAnalysis,
    ExecutiveSummary,
    DashboardStats,
    FeatureRequest
)

# ============================================================
# DATABASE SETUP
# ============================================================

# DB file lives at the project root
# __file__ = current file path (backend/database.py)
# os.path.dirname x2 = go up two levels to project root
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "transcript_intelligence.db"
)


def get_connection() -> sqlite3.Connection:
    """
    Creates and returns a database connection.
    
    Why row_factory = sqlite3.Row?
    By default sqlite3 returns plain tuples: (1, "support", 0.8)
    With Row factory it returns dict-like objects: row["call_type"] = "support"
    Much easier to work with throughout the codebase.
    
    Called every time we need to talk to the database.
    SQLite handles concurrent reads fine for our scale.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Access columns by name, not index
    return conn


def init_db():
    """
    Creates all tables if they don't exist yet.
    Called ONCE when the FastAPI app starts up.
    
    IF NOT EXISTS means running this twice is safe — 
    it won't wipe your data on server restart.
    
    TABLE DESIGN DECISIONS:
    - We store complex nested data (lists, dicts) as JSON strings
    - Simple scalar fields (strings, floats, bools) as native SQLite types
    - Every table has meeting_id as the primary key / foreign key
    - created_at on every table for audit trail (governance requirement)
    """
    conn = get_connection()
    cursor = conn.cursor()

    # ── Table 1: transcripts ──────────────────────────────────
    # Stores the processed transcript after ingestion agent runs.
    # full_text is the entire conversation joined — used for LLM context.
    # sentences_json stores the array of sentence objects for RAG chunking.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transcripts (
            meeting_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            call_type TEXT NOT NULL,
            start_time TEXT,
            duration_minutes REAL,
            organizer_email TEXT,
            all_emails TEXT,          -- JSON array stored as string
            full_text TEXT,           -- Entire transcript as one string
            summary TEXT,             -- Pre-existing summary from source data
            total_sentences INTEGER,
            positive_count INTEGER,
            negative_count INTEGER,
            neutral_count INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # ── Table 2: topic_analyses ───────────────────────────────
    # One row per transcript, produced by the Topic Discovery Agent.
    # themes and keywords are JSON arrays — we serialize before storing.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topic_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id TEXT NOT NULL,
            primary_topic TEXT NOT NULL,
            themes TEXT,              -- JSON array: ["Outage", "Remediation"]
            keywords TEXT,            -- JSON array: ["circuit breaker", "failover"]
            confidence REAL,
            reasoning TEXT,           -- LLM's explanation — explainability feature
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (meeting_id) REFERENCES transcripts(meeting_id)
        )
    """)

    # ── Table 3: sentiment_analyses ───────────────────────────
    # One row per transcript, produced by the Sentiment Agent.
    # sentiment_arc captures HOW sentiment changed during the call.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sentiment_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id TEXT NOT NULL,
            overall_sentiment TEXT NOT NULL,
            sentiment_score REAL,
            frustration_detected INTEGER,  -- SQLite has no bool; 0/1
            escalation_risk INTEGER,
            resolution_detected INTEGER,
            sentiment_arc TEXT,            -- JSON array: ["negative","neutral","positive"]
            key_moments TEXT,              -- JSON array of important sentences
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (meeting_id) REFERENCES transcripts(meeting_id)
        )
    """)

    # ── Table 4: risk_analyses ────────────────────────────────
    # One row per transcript, produced by the Churn Risk Agent.
    # citations stores exact transcript sentences as evidence.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS risk_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            risk_score REAL,
            churn_indicators TEXT,     -- JSON array
            competitor_mentions TEXT,  -- JSON array
            pricing_objections INTEGER,
            citations TEXT,            -- JSON array of exact sentences
            confidence REAL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (meeting_id) REFERENCES transcripts(meeting_id)
        )
    """)

    # ── Table 5: feature_requests ─────────────────────────────
    # Multiple rows per transcript (one per feature request found).
    # This table grows as the same feature appears across transcripts.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feature_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id TEXT NOT NULL,
            feature_description TEXT NOT NULL,
            requester_email TEXT,
            business_impact TEXT,
            frequency_count INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (meeting_id) REFERENCES transcripts(meeting_id)
        )
    """)

    # ── Table 6: executive_summaries ──────────────────────────
    # One row per transcript — the final combined output.
    # human_review_required is our governance flag.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS executive_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id TEXT NOT NULL,
            title TEXT,
            call_type TEXT,
            one_line_summary TEXT,
            key_findings TEXT,         -- JSON array
            recommendations TEXT,      -- JSON array
            human_review_required INTEGER,
            review_reason TEXT,
            processed_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (meeting_id) REFERENCES transcripts(meeting_id)
        )
    """)

    # ── Table 7: audit_logs ───────────────────────────────────
    # Every agent action gets logged here.
    # This is the AI Governance audit trail —
    # who ran what agent, on which transcript, at what time.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id TEXT,
            agent_name TEXT NOT NULL,   -- "topic_agent", "sentiment_agent" etc.
            action TEXT NOT NULL,       -- "analyze", "classify", "score"
            status TEXT NOT NULL,       -- "success", "failed", "skipped"
            details TEXT,               -- JSON with any extra context
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    conn.commit()
    conn.close()
    print(f"✅ Database initialized at: {DB_PATH}")


# ============================================================
# WRITE FUNCTIONS — Called by agents to save their output
# ============================================================

def save_transcript(t: ProcessedTranscript):
    """
    Saves a processed transcript to the database.
    
    INSERT OR REPLACE means if we re-run the pipeline,
    it updates existing records instead of crashing on duplicate keys.
    This makes the pipeline idempotent — safe to run multiple times.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO transcripts
        (meeting_id, title, call_type, start_time, duration_minutes,
         organizer_email, all_emails, full_text, summary,
         total_sentences, positive_count, negative_count, neutral_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        t.meeting_id,
        t.title,
        t.call_type.value,          # .value converts enum to string: "support"
        t.start_time,
        t.duration_minutes,
        t.organizer_email,
        json.dumps(t.all_emails),   # List → JSON string for storage
        t.full_text,
        t.summary,
        t.total_sentences,
        t.positive_sentence_count,
        t.negative_sentence_count,
        t.neutral_sentence_count
    ))
    conn.commit()
    conn.close()


def save_topic_analysis(ta: TopicAnalysis):
    """Saves topic analysis output. Called by Topic Discovery Agent."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO topic_analyses
        (meeting_id, primary_topic, themes, keywords, confidence, reasoning)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        ta.meeting_id,
        ta.primary_topic,
        json.dumps(ta.themes),      # ["Outage Response", "Infrastructure"] → JSON
        json.dumps(ta.keywords),
        ta.confidence,
        ta.reasoning
    ))
    conn.commit()
    conn.close()


def save_sentiment_analysis(sa: SentimentAnalysis):
    """Saves sentiment analysis output. Called by Sentiment Agent."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO sentiment_analyses
        (meeting_id, overall_sentiment, sentiment_score, frustration_detected,
         escalation_risk, resolution_detected, sentiment_arc, key_moments)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sa.meeting_id,
        sa.overall_sentiment.value,
        sa.sentiment_score,
        int(sa.frustration_detected),   # bool → int for SQLite
        int(sa.escalation_risk),
        int(sa.resolution_detected),
        json.dumps(sa.sentiment_arc),
        json.dumps(sa.key_moments)
    ))
    conn.commit()
    conn.close()


def save_risk_analysis(ra: RiskAnalysis):
    """Saves risk analysis output. Called by Churn Risk Agent."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO risk_analyses
        (meeting_id, risk_level, risk_score, churn_indicators,
         competitor_mentions, pricing_objections, citations, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        ra.meeting_id,
        ra.risk_level.value,
        ra.risk_score,
        json.dumps(ra.churn_indicators),
        json.dumps(ra.competitor_mentions),
        int(ra.pricing_objections),
        json.dumps(ra.citations),
        ra.confidence
    ))
    conn.commit()
    conn.close()


def save_executive_summary(es: ExecutiveSummary):
    """Saves executive summary. Called by Synthesis Agent."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO executive_summaries
        (meeting_id, title, call_type, one_line_summary, key_findings,
         recommendations, human_review_required, review_reason, processed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        es.meeting_id,
        es.title,
        es.call_type.value,
        es.one_line_summary,
        json.dumps(es.key_findings),
        json.dumps(es.recommendations),
        int(es.human_review_required),
        es.review_reason,
        es.processed_at
    ))
    conn.commit()
    conn.close()


def log_agent_action(meeting_id: str, agent_name: str,
                     action: str, status: str, details: dict = None):
    """
    Writes one row to audit_logs.
    Called by every agent after it finishes processing.
    
    This is our governance audit trail — every AI decision is logged
    with timestamp, agent name, and outcome.
    Enterprise security teams will love this.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO audit_logs (meeting_id, agent_name, action, status, details)
        VALUES (?, ?, ?, ?, ?)
    """, (
        meeting_id,
        agent_name,
        action,
        status,
        json.dumps(details) if details else None
    ))
    conn.commit()
    conn.close()


# ============================================================
# READ FUNCTIONS — Called by API endpoints
# ============================================================

def get_all_transcripts() -> list[dict]:
    """Returns all transcripts as a list of dicts for the API."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.*, 
               ta.primary_topic,
               sa.overall_sentiment, sa.sentiment_score,
               ra.risk_level, ra.risk_score
        FROM transcripts t
        LEFT JOIN topic_analyses ta ON t.meeting_id = ta.meeting_id
        LEFT JOIN sentiment_analyses sa ON t.meeting_id = sa.meeting_id
        LEFT JOIN risk_analyses ra ON t.meeting_id = ra.meeting_id
        ORDER BY t.start_time DESC
    """)
    # dict(row) converts sqlite3.Row to a plain Python dict
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_dashboard_stats() -> dict:
    """
    Computes aggregated stats for the dashboard page.
    Uses SQL aggregations — much faster than loading all rows into Python.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Total count + breakdown by call type
    cursor.execute("""
        SELECT call_type, COUNT(*) as count
        FROM transcripts
        GROUP BY call_type
    """)
    type_rows = cursor.fetchall()
    call_type_breakdown = {row["call_type"]: row["count"] for row in type_rows}
    total = sum(call_type_breakdown.values())

    # Average sentiment score across all transcripts
    cursor.execute("SELECT AVG(sentiment_score) as avg FROM sentiment_analyses")
    avg_sentiment = cursor.fetchone()["avg"] or 0.0

    # Count high risk transcripts
    cursor.execute("""
        SELECT COUNT(*) as count FROM risk_analyses WHERE risk_level = 'high'
    """)
    high_risk = cursor.fetchone()["count"]

    # Total feature requests
    cursor.execute("SELECT COUNT(*) as count FROM feature_requests")
    feature_count = cursor.fetchone()["count"]

    # Pending human reviews
    cursor.execute("""
        SELECT COUNT(*) as count FROM executive_summaries
        WHERE human_review_required = 1
    """)
    review_count = cursor.fetchone()["count"]

    conn.close()

    return {
        "total_transcripts": total,
        "call_type_breakdown": call_type_breakdown,
        "avg_sentiment_score": round(avg_sentiment, 3),
        "high_risk_count": high_risk,
        "total_feature_requests": feature_count,
        "human_review_pending": review_count
    }


def get_transcript_by_id(meeting_id: str) -> Optional[dict]:
    """Fetches one transcript with all its analysis joined."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.*, 
               ta.primary_topic, ta.themes, ta.keywords, ta.reasoning,
               sa.overall_sentiment, sa.sentiment_score, sa.frustration_detected,
               sa.escalation_risk, sa.sentiment_arc, sa.key_moments,
               ra.risk_level, ra.risk_score, ra.churn_indicators, ra.citations,
               es.one_line_summary, es.key_findings, es.recommendations,
               es.human_review_required, es.review_reason
        FROM transcripts t
        LEFT JOIN topic_analyses ta ON t.meeting_id = ta.meeting_id
        LEFT JOIN sentiment_analyses sa ON t.meeting_id = sa.meeting_id
        LEFT JOIN risk_analyses ra ON t.meeting_id = ra.meeting_id
        LEFT JOIN executive_summaries es ON t.meeting_id = es.meeting_id
        WHERE t.meeting_id = ?
    """, (meeting_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_audit_logs(meeting_id: str = None) -> list[dict]:
    """
    Returns audit logs — optionally filtered by meeting_id.
    Used by the Evaluations page to show AI governance trail.
    """
    conn = get_connection()
    cursor = conn.cursor()
    if meeting_id:
        cursor.execute("""
            SELECT * FROM audit_logs WHERE meeting_id = ?
            ORDER BY created_at DESC
        """, (meeting_id,))
    else:
        cursor.execute("SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT 100")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows