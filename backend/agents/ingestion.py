# backend/agents/ingestion.py
# ============================================================
# INGESTION AGENT
# ============================================================
# RESPONSIBILITY:
#   1. Read all 6 JSON files for one transcript folder
#   2. Infer the call type (support/external/internal)
#      because the raw data has NO call_type field
#   3. Assemble everything into a clean ProcessedTranscript
#   4. Save it to the database
#   5. Log the action to audit trail
#
# WHY THIS IS ITS OWN AGENT:
#   Separation of concerns. If the raw data format changes
#   (e.g. a new field is added), only THIS file changes.
#   Nothing else in the pipeline needs to know about raw JSON.
#
# CALLED BY: pipeline.py (LangGraph orchestration)
# OUTPUT: ProcessedTranscript (defined in models.py)
# ============================================================

import os
import json
from backend.models import (
    ProcessedTranscript,
    TranscriptSentence,
    CallType
)
from backend.database import save_transcript, log_agent_action


# ============================================================
# CALL TYPE INFERENCE LOGIC
# ============================================================

def infer_call_type(title: str, all_emails: list[str]) -> CallType:
    """
    Infers call type from meeting title and participant emails.
    
    WHY RULE-BASED AND NOT LLM-BASED HERE?
    This is a cheap, deterministic classification.
    Using an LLM for this would cost money and add latency
    for something we can solve with simple logic.
    Senior engineering principle: use the simplest tool that works.
    
    LOGIC:
    1. Title contains "Support Case" → SUPPORT
       (AegisCloud's support team uses this naming convention)
    
    2. All emails share the same domain → INTERNAL
       (only company employees = internal meeting)
    
    3. Mixed domains (company + customer) → EXTERNAL
       (account manager + customer = external call)
    """

    # Rule 1: Support calls have explicit "Support Case" in title
    title_lower = title.lower()
    support_keywords = ["support case", "support ticket", "help desk", "incident"]
    if any(kw in title_lower for kw in support_keywords):
        return CallType.SUPPORT

    # Rule 2: Check email domains
    # Extract domain from each email: "raj@aegiscloud.com" → "aegiscloud.com"
    domains = set()
    for email in all_emails:
        if "@" in email:
            domain = email.split("@")[1].lower()
            domains.add(domain)

    # If only one unique domain → everyone is from same company → INTERNAL
    if len(domains) == 1:
        return CallType.INTERNAL

    # Rule 3: Multiple domains = external customer call
    return CallType.EXTERNAL


# ============================================================
# FILE READERS
# ============================================================

def read_json_file(folder_path: str, filename: str) -> dict | list | None:
    """
    Safely reads one JSON file from a transcript folder.
    
    Returns None if file doesn't exist rather than crashing.
    WHY: Not every folder has every file. Defensive programming
    means the pipeline keeps running even with incomplete data.
    """
    filepath = os.path.join(folder_path, filename)
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_full_text(sentences: list[dict]) -> str:
    """
    Joins all sentences into one continuous text string.
    
    Format: "SpeakerName: sentence text\n"
    
    WHY THIS FORMAT?
    When we pass this to the LLM for topic/sentiment analysis,
    the speaker labels help the model understand who said what.
    "Raj Kapoor: We had a complete outage for 6 hours" is more
    informative than just "We had a complete outage for 6 hours"
    """
    lines = []
    for s in sentences:
        speaker = s.get("speaker_name", "Unknown")
        sentence = s.get("sentence", "")
        lines.append(f"{speaker}: {sentence}")
    return "\n".join(lines)


def compute_sentiment_counts(sentences: list[dict]) -> tuple[int, int, int]:
    """
    Counts positive/negative/neutral sentences from existing labels.
    
    The transcript.json already has sentimentType on each sentence.
    We just aggregate them — no LLM needed.
    
    Returns: (positive_count, negative_count, neutral_count)
    """
    positive = sum(1 for s in sentences if s.get("sentimentType") == "positive")
    negative = sum(1 for s in sentences if s.get("sentimentType") == "negative")
    neutral = sum(1 for s in sentences if s.get("sentimentType") == "neutral")
    return positive, negative, neutral


# ============================================================
# MAIN INGESTION FUNCTION
# ============================================================

def ingest_transcript(folder_path: str) -> ProcessedTranscript | None:
    """
    Main function — processes ONE transcript folder end to end.
    
    FLOW:
    folder_path (e.g. dataset/01KQ03B...) 
        → read 6 JSON files
        → infer call type
        → build ProcessedTranscript
        → save to database
        → log to audit trail
        → return ProcessedTranscript for downstream agents
    
    Returns None if the folder is missing critical files,
    so the pipeline can skip it and continue with others.
    """
    meeting_id = os.path.basename(folder_path)  # Folder name = meeting ID

    try:
        # ── Step 1: Read all JSON files ───────────────────────
        meeting_info = read_json_file(folder_path, "meeting-info.json")
        transcript_data = read_json_file(folder_path, "transcript.json")
        summary_data = read_json_file(folder_path, "summary.json")

        # Critical files — if missing, skip this transcript
        if not meeting_info or not transcript_data:
            log_agent_action(
                meeting_id=meeting_id,
                agent_name="ingestion_agent",
                action="ingest",
                status="skipped",
                details={"reason": "Missing meeting-info.json or transcript.json"}
            )
            return None

        # ── Step 2: Extract raw sentences ─────────────────────
        # transcript.json structure: {"data": [...sentences]}
        raw_sentences = transcript_data.get("data", [])
        if not raw_sentences:
            return None

        # ── Step 3: Parse sentences into Pydantic models ──────
        # We wrap each dict in TranscriptSentence for validation
        # model_validate() is Pydantic v2's way to create from dict
        sentences = []
        for s in raw_sentences:
            try:
                sentences.append(TranscriptSentence.model_validate(s))
            except Exception:
                # If one sentence is malformed, skip it, don't crash
                continue

        # ── Step 4: Build derived fields ──────────────────────
        full_text = extract_full_text(raw_sentences)
        positive, negative, neutral = compute_sentiment_counts(raw_sentences)

        # Extract summary text from summary.json
        # It could be a string or {"summary": "..."} depending on format
        if isinstance(summary_data, dict):
            summary_text = summary_data.get("summary", "")
        elif isinstance(summary_data, str):
            summary_text = summary_data
        else:
            summary_text = ""

        # ── Step 5: Infer call type ────────────────────────────
        all_emails = meeting_info.get("allEmails", [])
        title = meeting_info.get("title", "Untitled")
        call_type = infer_call_type(title, all_emails)

        # ── Step 6: Assemble ProcessedTranscript ──────────────
        processed = ProcessedTranscript(
            meeting_id=meeting_id,
            title=title,
            call_type=call_type,
            start_time=meeting_info.get("startTime", ""),
            duration_minutes=meeting_info.get("duration", 0.0),
            organizer_email=meeting_info.get("organizerEmail", ""),
            all_emails=all_emails,
            participant_count=len(all_emails),
            full_text=full_text,
            sentences=sentences,
            summary=summary_text,
            total_sentences=len(sentences),
            positive_sentence_count=positive,
            negative_sentence_count=negative,
            neutral_sentence_count=neutral
        )

        # ── Step 7: Save to database ───────────────────────────
        save_transcript(processed)

        # ── Step 8: Log success to audit trail ────────────────
        log_agent_action(
            meeting_id=meeting_id,
            agent_name="ingestion_agent",
            action="ingest",
            status="success",
            details={
                "call_type": call_type.value,
                "sentence_count": len(sentences),
                "duration_minutes": processed.duration_minutes
            }
        )

        print(f"  ✅ Ingested: {title[:50]} [{call_type.value}]")
        return processed

    except Exception as e:
        # Log failure but don't crash the whole pipeline
        log_agent_action(
            meeting_id=meeting_id,
            agent_name="ingestion_agent",
            action="ingest",
            status="failed",
            details={"error": str(e)}
        )
        print(f"  ❌ Failed to ingest {meeting_id}: {e}")
        return None


# ============================================================
# BATCH INGESTION — Processes all folders in dataset
# ============================================================

def ingest_all_transcripts(dataset_path: str) -> list[ProcessedTranscript]:
    """
    Runs ingest_transcript() on every folder in the dataset.
    
    Returns a list of successfully processed transcripts.
    Failed ones are logged but don't stop the pipeline.
    
    CALLED BY: pipeline.py at the start of the LangGraph workflow.
    """
    print(f"\n🔄 Starting ingestion from: {dataset_path}")

    # Get all subdirectories = one per transcript
    folders = sorted([
        os.path.join(dataset_path, f)
        for f in os.listdir(dataset_path)
        if os.path.isdir(os.path.join(dataset_path, f))
        and not f.startswith(".")
        and not f.startswith("__")
    ])

    print(f"📁 Found {len(folders)} transcript folders\n")

    results = []
    for i, folder_path in enumerate(folders, 1):
        print(f"[{i}/{len(folders)}] Processing...", end=" ")
        transcript = ingest_transcript(folder_path)
        if transcript:
            results.append(transcript)

    # Summary
    print(f"\n📊 Ingestion complete:")
    print(f"   ✅ Success: {len(results)}/{len(folders)}")
    print(f"   ❌ Failed:  {len(folders) - len(results)}/{len(folders)}")

    # Print call type breakdown
    from collections import Counter
    type_counts = Counter(t.call_type.value for t in results)
    print(f"\n📞 Call type breakdown:")
    for call_type, count in sorted(type_counts.items()):
        print(f"   {call_type}: {count}")

    return results