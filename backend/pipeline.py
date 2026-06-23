# backend/pipeline.py
# ============================================================
# LANGGRAPH PIPELINE ORCHESTRATION
# ============================================================
# This file defines the multi-agent pipeline as a LangGraph
# StateGraph — a directed acyclic graph where each node
# is one agent, and edges define the data flow.
#
# WHY LANGGRAPH:
#   LangGraph gives us explicit state management between agents.
#   Each node receives the current state, does its work, and
#   returns an updated state. This makes the pipeline:
#   - Inspectable (you can see state at any node)
#   - Resumable (can restart from any checkpoint)
#   - Testable (each node is independently testable)
#
# PIPELINE FLOW:
#   ingest → topic → sentiment → risk → synthesis → END
#
# STATE:
#   PipelineState holds everything produced by each agent.
#   It flows through the entire graph, accumulating results.
# ============================================================

import os
from typing import TypedDict, Optional
from dotenv import load_dotenv

# LangGraph imports
from langgraph.graph import StateGraph, END

# Our agent functions
from backend.agents.ingestion import ingest_transcript
from backend.agents.topic import analyze_topic
from backend.agents.sentiment import analyze_sentiment
from backend.agents.risk import analyze_risk
from backend.agents.synthesis import synthesize

# Our data models
from backend.models import (
    ProcessedTranscript,
    TopicAnalysis,
    SentimentAnalysis,
    RiskAnalysis,
    ExecutiveSummary
)

load_dotenv()


# ============================================================
# PIPELINE STATE
# ============================================================

class PipelineState(TypedDict):
    """
    The state object that flows through every node in the graph.

    WHY TypedDict:
    LangGraph requires state to be a TypedDict.
    Each agent reads what it needs and writes its output.
    Optional fields start as None and get populated as
    the pipeline progresses.

    Think of this as a "baton" passed between runners
    in a relay race — each runner adds to it.
    """
    folder_path: str                              # Input: path to transcript folder
    meeting_id: str                               # Extracted from folder name
    transcript: Optional[ProcessedTranscript]     # Set by ingestion agent
    topic: Optional[TopicAnalysis]                # Set by topic agent
    sentiment: Optional[SentimentAnalysis]        # Set by sentiment agent
    risk: Optional[RiskAnalysis]                  # Set by risk agent
    summary: Optional[ExecutiveSummary]           # Set by synthesis agent
    error: Optional[str]                          # Set if any agent fails


# ============================================================
# AGENT NODES
# ============================================================
# Each function below is a "node" in the LangGraph graph.
# Nodes receive the current state and return updated state.
# The return dict is MERGED into the existing state —
# you only need to return the fields you're updating.

def ingestion_node(state: PipelineState) -> dict:
    """
    Node 1: Ingestion Agent
    Reads all 6 JSON files, infers call type, builds ProcessedTranscript.
    """
    print(f"  [1/5] Ingesting: {state['meeting_id'][:16]}...")
    transcript = ingest_transcript(state["folder_path"])
    if not transcript:
        return {"error": "Ingestion failed — missing or malformed files"}
    return {"transcript": transcript}


def topic_node(state: PipelineState) -> dict:
    """
    Node 2: Topic Discovery Agent
    Classifies transcript into one of 12 topic categories.
    Skipped if ingestion failed.
    """
    if state.get("error") or not state.get("transcript"):
        return {}  # Skip — don't add to error, just pass through
    print(f"  [2/5] Classifying topic...")
    topic = analyze_topic(state["transcript"])
    return {"topic": topic}


def sentiment_node(state: PipelineState) -> dict:
    """
    Node 3: Sentiment Intelligence Agent
    Hybrid approach: math for score/arc, LLM for frustration/escalation.
    """
    if state.get("error") or not state.get("transcript"):
        return {}
    print(f"  [3/5] Analyzing sentiment...")
    sentiment = analyze_sentiment(state["transcript"])
    return {"sentiment": sentiment}


def risk_node(state: PipelineState) -> dict:
    """
    Node 4: Churn Risk Agent
    Skips internal calls (no customer = no churn risk).
    Hybrid: keyword scan + LLM for citations.
    """
    if state.get("error") or not state.get("transcript"):
        return {}
    print(f"  [4/5] Scoring risk...")
    risk = analyze_risk(state["transcript"])
    return {"risk": risk}


def synthesis_node(state: PipelineState) -> dict:
    """
    Node 5: Executive Synthesis Agent
    Combines all agent outputs into one leadership-ready summary.
    Sets human_review_required flag based on governance rules.
    """
    if state.get("error"):
        return {}
    if not all([state.get("transcript"), state.get("topic"),
                state.get("sentiment"), state.get("risk")]):
        return {"error": "Cannot synthesize — missing upstream agent output"}

    print(f"  [5/5] Synthesizing executive summary...")
    summary = synthesize(
        state["transcript"],
        state["topic"],
        state["sentiment"],
        state["risk"]
    )
    return {"summary": summary}


# ============================================================
# CONDITIONAL ROUTING
# ============================================================

def should_continue(state: PipelineState) -> str:
    """
    Router function — decides whether to continue or stop.

    LangGraph uses these to implement conditional edges:
    if error → go to END
    if no transcript → go to END
    otherwise → continue to next node

    This prevents downstream agents from running on
    bad data and wasting API calls.
    """
    if state.get("error"):
        print(f"  ⚠️  Pipeline stopping: {state['error']}")
        return "end"
    if not state.get("transcript"):
        return "end"
    return "continue"


# ============================================================
# GRAPH CONSTRUCTION
# ============================================================

def build_pipeline() -> StateGraph:
    """
    Constructs the LangGraph StateGraph.

    GRAPH STRUCTURE:
    ingest_node
        ↓ (conditional: if error → END)
    topic_node
        ↓
    sentiment_node
        ↓
    risk_node
        ↓
    synthesis_node
        ↓
    END

    WHY CONDITIONAL EDGES after ingestion:
    If a transcript folder is missing critical files,
    we stop immediately rather than calling the LLM 4 times
    on empty data and wasting money.
    """
    # Initialize graph with our state schema
    graph = StateGraph(PipelineState)

    # Add nodes — each corresponds to one agent
    graph.add_node("ingest", ingestion_node)
    graph.add_node("topic", topic_node)
    graph.add_node("sentiment", sentiment_node)
    graph.add_node("risk", risk_node)
    graph.add_node("synthesis", synthesis_node)

    # Set entry point — where the graph starts
    graph.set_entry_point("ingest")

    # Conditional edge after ingestion
    # If ingestion fails → END, otherwise → topic
    graph.add_conditional_edges(
        "ingest",
        should_continue,
        {
            "continue": "topic",
            "end": END
        }
    )

    # Linear edges for the rest of the pipeline
    # These always proceed regardless of individual agent failures
    # (each node handles its own missing-state gracefully)
    graph.add_edge("topic", "sentiment")
    graph.add_edge("sentiment", "risk")
    graph.add_edge("risk", "synthesis")
    graph.add_edge("synthesis", END)

    return graph.compile()


# ============================================================
# PIPELINE RUNNER
# ============================================================

def run_pipeline(folder_path: str) -> PipelineState:
    """
    Runs the complete pipeline for ONE transcript folder.

    Returns the final PipelineState containing all agent outputs.
    The caller can inspect any field: state['topic'], state['risk'], etc.

    Usage:
        state = run_pipeline("dataset/01KQ03B...")
        print(state['summary'].one_line_summary)
    """
    pipeline = build_pipeline()
    meeting_id = os.path.basename(folder_path)

    # Initial state — only folder_path and meeting_id populated
    # All agent outputs start as None
    initial_state: PipelineState = {
        "folder_path": folder_path,
        "meeting_id": meeting_id,
        "transcript": None,
        "topic": None,
        "sentiment": None,
        "risk": None,
        "summary": None,
        "error": None,
    }

    # Run the graph — returns final state after all nodes execute
    final_state = pipeline.invoke(initial_state)
    return final_state


def run_pipeline_batch(dataset_path: str) -> list[PipelineState]:
    """
    Runs the pipeline on ALL transcript folders in a dataset.

    This is the production entry point — used by main.py on startup.
    Each transcript gets its own independent pipeline run.
    Failed transcripts don't affect others.

    Returns list of final states for inspection/testing.
    """
    from backend.database import init_db
    init_db()

    folders = sorted([
        os.path.join(dataset_path, f)
        for f in os.listdir(dataset_path)
        if os.path.isdir(os.path.join(dataset_path, f))
        and not f.startswith(".")
        and not f.startswith("__")
    ])

    print(f"\n🔄 Running LangGraph pipeline on {len(folders)} transcripts...")
    results = []

    for i, folder_path in enumerate(folders, 1):
        meeting_id = os.path.basename(folder_path)
        print(f"\n[{i}/{len(folders)}] {meeting_id[:20]}...")
        state = run_pipeline(folder_path)
        results.append(state)

        # Report outcome
        if state.get("error"):
            print(f"  ❌ {state['error']}")
        elif state.get("summary"):
            print(f"  ✅ {state['summary'].one_line_summary[:60]}")

    successful = sum(1 for s in results if s.get("summary"))
    print(f"\n✅ Pipeline complete: {successful}/{len(folders)} succeeded")
    return results


# ============================================================
# DIRECT EXECUTION (for testing)
# ============================================================

if __name__ == "__main__":
    """
    Run this file directly to test the pipeline on 3 transcripts:
    python -m backend.pipeline
    """
    dataset_path = os.getenv(
        "DATASET_PATH",
        r"D:\Downloads\interview-assignment\interview-assignment\dataset"
    )

    # Test on first 3 folders only
    folders = sorted([
        f for f in os.listdir(dataset_path)
        if os.path.isdir(os.path.join(dataset_path, f))
    ])[:3]

    print("Testing LangGraph pipeline on 3 transcripts...")
    for folder in folders:
        folder_path = os.path.join(dataset_path, folder)
        state = run_pipeline(folder_path)
        if state.get("summary"):
            print(f"\n✅ {state['summary'].title}")
            print(f"   Topic: {state['topic'].primary_topic}")
            print(f"   Risk: {state['risk'].risk_level.value}")
            print(f"   Summary: {state['summary'].one_line_summary}")