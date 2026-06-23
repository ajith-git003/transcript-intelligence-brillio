# backend/models.py
# ============================================================
# DATA MODELS FOR TRANSCRIPT INTELLIGENCE PLATFORM
# ============================================================
# We use Pydantic v2 for all data models.
# Pydantic does two things for us:
#   1. Validates data shapes (catches bugs early)
#   2. Auto-generates JSON schemas (FastAPI uses these for docs)
# Think of these as "contracts" between every part of the system.
# ============================================================

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


# ============================================================
# ENUMS — Fixed set of allowed values
# ============================================================

class CallType(str, Enum):
    """
    The three call types the assignment asks us to classify.
    We inherit from str so it serializes to "support" not "CallType.support"
    which matters when we store it in SQLite or return it via API.
    """
    SUPPORT = "support"       # Customer reaching out with issues
    EXTERNAL = "external"     # Account manager + customer (renewals, feedback)
    INTERNAL = "internal"     # Engineering syncs, planning, escalations


class SentimentType(str, Enum):
    """
    Maps directly to the sentimentType field already in transcript.json.
    Having it as an Enum means if the data has a typo, Pydantic catches it.
    """
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class RiskLevel(str, Enum):
    """
    Churn risk levels produced by the Risk Agent.
    LOW/MEDIUM/HIGH is the classic 3-tier used in B2B SaaS health scoring.
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ============================================================
# RAW DATA MODELS — What we read from the JSON files
# ============================================================

class TranscriptSentence(BaseModel):
    """
    One sentence from transcript.json → data[] array.
    Each sentence already has sentiment + speaker + timestamp.
    We'll use these sentences as the unit for RAG chunking later.
    """
    sentence: str
    speaker_name: str
    sentiment_type: str = Field(alias="sentimentType")
    speaker_id: int
    time: float                          # Start time in seconds
    end_time: float = Field(alias="endTime")
    average_confidence: float = Field(alias="averageConfidence")
    index: int

    model_config = {"populate_by_name": True}
    # populate_by_name=True means we can use either
    # "sentimentType" (original JSON) or "sentiment_type" (our Python style)


class MeetingInfo(BaseModel):
    """
    From meeting-info.json.
    Notice there's NO call_type field in the raw data —
    we have to infer it ourselves from title + email domains.
    That inference logic lives in the Ingestion Agent.
    """
    meeting_id: str = Field(alias="meetingId")
    title: str
    organizer_email: str = Field(alias="organizerEmail")
    host: str
    start_time: str = Field(alias="startTime")
    end_time: str = Field(alias="endTime")
    duration: float                      # Minutes
    all_emails: list[str] = Field(alias="allEmails")

    model_config = {"populate_by_name": True}


# ============================================================
# PROCESSED MODELS — What our agents produce
# ============================================================

class ProcessedTranscript(BaseModel):
    """
    The single most important model in the system.
    This is what one transcript looks like AFTER the ingestion agent
    has read all 6 JSON files and assembled them into one clean object.
    
    Every downstream agent (Topic, Sentiment, Risk) receives this.
    Think of it as the "enriched record" that flows through LangGraph.
    """
    # Identity
    meeting_id: str
    title: str
    
    # Classification (inferred by ingestion agent)
    call_type: CallType
    
    # Timing
    start_time: str
    duration_minutes: float
    
    # People
    organizer_email: str
    all_emails: list[str]
    participant_count: int
    
    # Content
    full_text: str           # All sentences joined — used for LLM analysis
    sentences: list[TranscriptSentence]   # Used for RAG chunking
    summary: str             # Pre-existing summary from summary.json
    
    # Pre-computed stats (cheap, no LLM needed)
    total_sentences: int
    positive_sentence_count: int
    negative_sentence_count: int
    neutral_sentence_count: int


class TopicAnalysis(BaseModel):
    """
    Output of the Topic Discovery Agent for one transcript.
    
    primary_topic: The single best label (e.g. "Outage Response")
    themes: Supporting sub-topics found in the conversation
    keywords: Important words extracted — used for search + display
    confidence: How sure the LLM is (0.0 to 1.0)
                This is part of our AI Governance layer —
                low confidence triggers a human review flag.
    """
    meeting_id: str
    primary_topic: str
    themes: list[str]
    keywords: list[str]
    confidence: float = Field(ge=0.0, le=1.0)  # ge=greater or equal, le=less or equal
    reasoning: str           # WHY the LLM chose this topic — explainability


class SentimentAnalysis(BaseModel):
    """
    Output of the Sentiment Intelligence Agent for one transcript.
    
    We go beyond simple positive/negative:
    - overall_sentiment: The dominant tone of the whole call
    - frustration_detected: Boolean flag for support/escalation workflows
    - escalation_risk: Should a manager review this call?
    - sentiment_arc: How did sentiment CHANGE during the call?
                     e.g. ["negative", "neutral", "positive"] = resolved well
    """
    meeting_id: str
    overall_sentiment: SentimentType
    sentiment_score: float = Field(ge=-1.0, le=1.0)  # -1=very negative, +1=very positive
    frustration_detected: bool
    escalation_risk: bool
    resolution_detected: bool        # Did the call end with a resolution?
    sentiment_arc: list[str]         # Sentiment progression through the call
    key_moments: list[str]           # Notable sentences that drove the sentiment


class RiskAnalysis(BaseModel):
    """
    Output of the Churn Risk Agent for one transcript.
    Only meaningful for EXTERNAL call types (customer calls).
    For internal calls, risk_level defaults to LOW with a note.
    
    risk_score: 0-100 numeric score (useful for ranking/sorting)
    risk_level: LOW/MEDIUM/HIGH derived from risk_score
    indicators: Specific evidence found in the transcript
                e.g. ["Mentioned competitor Crowdstrike", "Asked about pricing"]
    citations: The EXACT sentences that triggered the risk flag
               This is our governance/explainability feature —
               a human reviewer can verify the AI's reasoning.
    """
    meeting_id: str
    risk_level: RiskLevel
    risk_score: float = Field(ge=0.0, le=100.0)
    churn_indicators: list[str]
    competitor_mentions: list[str]
    pricing_objections: bool
    citations: list[str]             # Exact transcript sentences as evidence
    confidence: float = Field(ge=0.0, le=1.0)


class FeatureRequest(BaseModel):
    """
    A single feature request extracted from any transcript.
    Multiple requests can come from one transcript.
    """
    feature_description: str
    requester_email: str
    meeting_id: str
    business_impact: str             # Why they want it (from context)
    frequency_count: int = 1         # Incremented when same feature appears elsewhere


class ExecutiveSummary(BaseModel):
    """
    Output of the Synthesis Agent — combines ALL other agent outputs
    into a leadership-ready summary for ONE transcript.
    
    This is what shows up on the Dashboard and in the AI Chat responses.
    recommendations: Actionable next steps — the "so what" that leadership wants.
    human_review_required: True if any agent flagged low confidence or high risk.
    """
    meeting_id: str
    title: str
    call_type: CallType
    one_line_summary: str            # Tweet-length summary for dashboard cards
    key_findings: list[str]          # 3-5 bullet points
    recommendations: list[str]       # Actionable next steps
    topic: TopicAnalysis
    sentiment: SentimentAnalysis
    risk: RiskAnalysis
    feature_requests: list[FeatureRequest]
    human_review_required: bool      # Governance flag
    review_reason: Optional[str]     # Why review is needed, if applicable
    processed_at: str                # ISO timestamp — audit trail


# ============================================================
# API RESPONSE MODELS — What the frontend receives
# ============================================================

class DashboardStats(BaseModel):
    """
    Powers the main dashboard page.
    Aggregated across ALL 100 transcripts.
    """
    total_transcripts: int
    call_type_breakdown: dict[str, int]   # {"support": 35, "external": 40, "internal": 25}
    avg_sentiment_score: float
    high_risk_count: int
    total_feature_requests: int
    human_review_pending: int


class ChatMessage(BaseModel):
    """
    For the AI Chat page.
    role: "user" or "assistant"
    sources: Which transcripts were retrieved to answer this question.
             This is our citation/traceability governance feature.
    """
    role: str
    content: str
    sources: Optional[list[str]] = None   # meeting_ids used as context
    