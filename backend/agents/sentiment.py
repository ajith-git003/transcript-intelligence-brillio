# backend/agents/sentiment.py
# ============================================================
# SENTIMENT INTELLIGENCE AGENT
# ============================================================
# RESPONSIBILITY:
#   Goes BEYOND the per-sentence sentiment already in the data.
#   The raw data has sentence-level labels (positive/negative/neutral).
#   This agent produces CALL-LEVEL intelligence:
#   - overall_sentiment: dominant tone of entire call
#   - sentiment_score: -1.0 to +1.0 numeric score
#   - frustration_detected: is the customer frustrated?
#   - escalation_risk: should a manager review this?
#   - resolution_detected: did the call end positively?
#   - sentiment_arc: how did emotion CHANGE during the call?
#   - key_moments: the specific sentences that drove sentiment
#
# WHY THIS IS MORE VALUABLE THAN RAW SENTENCE LABELS:
#   A call can have 80% neutral sentences but still be a
#   high-risk call if the 20% negative sentences are intense.
#   Arc detection catches "started bad, ended resolved" vs
#   "started okay, ended angry" — totally different outcomes.
#
# CALLED BY: pipeline.py
# INPUT: ProcessedTranscript
# OUTPUT: SentimentAnalysis (saved to DB)
# ============================================================

import json
from openai import OpenAI
from backend.models import (
    ProcessedTranscript,
    SentimentAnalysis,
    SentimentType
)
from backend.database import save_sentiment_analysis, log_agent_action
from dotenv import load_dotenv
load_dotenv()

client = OpenAI()


# ============================================================
# PRE-COMPUTATION (No LLM needed)
# ============================================================

def compute_sentiment_score(
    positive: int,
    negative: int,
    neutral: int
) -> float:
    """
    Converts sentence counts into a -1.0 to +1.0 score.
    
    FORMULA:
    score = (positive - negative) / total_sentences
    
    WHY THIS FORMULA:
    - Pure positive call: (100 - 0) / 100 = +1.0
    - Pure negative call: (0 - 100) / 100 = -1.0
    - Neutral call: (0 - 0) / 100 = 0.0
    - Mixed call: (30 - 20) / 100 = +0.1 (slightly positive)
    
    This is a weighted score that accounts for neutral sentences
    naturally — they don't push the score in either direction.
    No LLM needed, deterministic, fast, free.
    """
    total = positive + negative + neutral
    if total == 0:
        return 0.0
    return round((positive - negative) / total, 3)


def build_sentiment_arc(sentences: list) -> list[str]:
    """
    Divides the call into thirds and computes dominant sentiment
    for each third. This gives us the emotional trajectory.
    
    Examples:
    ["negative", "negative", "positive"] = escalation resolved
    ["neutral", "negative", "negative"]  = deteriorating call
    ["positive", "positive", "positive"] = consistently good
    
    WHY THIRDS AND NOT EVERY SENTENCE:
    Sentence-level arc would be too noisy (flickering labels).
    Thirds give a clean 3-point narrative that's easy to explain.
    """
    if not sentences:
        return ["neutral"]

    total = len(sentences)
    third = max(1, total // 3)

    # Split sentences into beginning, middle, end
    segments = [
        sentences[:third],
        sentences[third:2*third],
        sentences[2*third:]
    ]

    arc = []
    for segment in segments:
        if not segment:
            continue
        # Count sentiments in this segment
        pos = sum(1 for s in segment if s.sentiment_type == "positive")
        neg = sum(1 for s in segment if s.sentiment_type == "negative")
        neu = sum(1 for s in segment if s.sentiment_type == "neutral")

        # Dominant sentiment wins
        if pos >= neg and pos >= neu:
            arc.append("positive")
        elif neg >= pos and neg >= neu:
            arc.append("negative")
        else:
            arc.append("neutral")

    return arc if arc else ["neutral"]


# ============================================================
# PROMPT BUILDER
# ============================================================

def build_sentiment_prompt(transcript: ProcessedTranscript) -> str:
    """
    We send THREE things to the LLM:
    1. Pre-computed stats (positive/negative/neutral counts)
       — gives the LLM hard numbers to anchor on
    2. The summary — high-level context
    3. The most emotionally charged sentences — extracted cheaply
       by filtering for negative/positive labeled sentences
    
    WHY NOT SEND THE FULL TRANSCRIPT?
    We already computed counts and arc from the raw labels.
    The LLM only needs to do what rule-based logic CAN'T:
    - Detect frustration (tone, word choice, not just labels)
    - Identify escalation risk (context-dependent)
    - Find the key moments (which specific sentences matter)
    - Judge resolution (did the call end well?)
    """
    # Extract the most emotionally charged sentences for context
    # These are the sentences most likely to carry signal
    charged_sentences = [
        s for s in transcript.sentences
        if s.sentiment_type in ["positive", "negative"]
    ][:15]  # Cap at 15 to control token cost

    charged_text = "\n".join([
        f"[{s.sentiment_type.upper()}] {s.speaker_name}: {s.sentence}"
        for s in charged_sentences
    ])

    # Pre-computed stats — no need for LLM to re-derive these
    total = transcript.total_sentences
    pos_pct = round(transcript.positive_sentence_count / total * 100) if total > 0 else 0
    neg_pct = round(transcript.negative_sentence_count / total * 100) if total > 0 else 0

    return f"""You are an expert customer success analyst specializing in B2B SaaS call analysis.

MEETING: {transcript.title}
CALL TYPE: {transcript.call_type.value}
DURATION: {transcript.duration_minutes:.1f} minutes

PRE-COMPUTED SENTIMENT STATS:
- Total sentences: {total}
- Positive: {transcript.positive_sentence_count} ({pos_pct}%)
- Negative: {transcript.negative_sentence_count} ({neg_pct}%)
- Neutral: {transcript.neutral_sentence_count}

SUMMARY:
{transcript.summary}

MOST EMOTIONALLY CHARGED SENTENCES:
{charged_text}

Analyze the sentiment of this call and respond with ONLY valid JSON:

{{
    "overall_sentiment": "<positive|negative|neutral>",
    "frustration_detected": <true|false>,
    "escalation_risk": <true|false>,
    "resolution_detected": <true|false>,
    "key_moments": [
        "<exact sentence or short quote that most impacted sentiment>",
        "<another key moment>",
        "<up to 3 total>"
    ],
    "reasoning": "<1-2 sentences explaining the overall sentiment judgment>"
}}

Guidelines:
- frustration_detected: true if customer expressed frustration, urgency, or dissatisfaction
- escalation_risk: true if this call needs manager/leadership attention
- resolution_detected: true if the issue was resolved or the call ended positively
- key_moments: use EXACT quotes from the transcript, keep them short
- For internal calls, assess team morale and alignment instead of customer sentiment"""


# ============================================================
# MAIN ANALYSIS FUNCTION
# ============================================================

def analyze_sentiment(
    transcript: ProcessedTranscript
) -> SentimentAnalysis | None:
    """
    Combines rule-based pre-computation with LLM analysis.
    
    HYBRID APPROACH:
    - sentiment_score: pure math (free, fast, deterministic)
    - sentiment_arc: rule-based on existing labels (free, fast)
    - frustration/escalation/resolution: LLM (needs context understanding)
    - key_moments: LLM (needs to identify what matters)
    
    This is a deliberate engineering decision:
    Use LLM only for what requires actual language understanding.
    Use math/rules for everything else.
    This keeps costs low and explainability high.
    """
    meeting_id = transcript.meeting_id

    try:
        # ── Step 1: Pre-compute without LLM ───────────────────
        sentiment_score = compute_sentiment_score(
            transcript.positive_sentence_count,
            transcript.negative_sentence_count,
            transcript.neutral_sentence_count
        )
        sentiment_arc = build_sentiment_arc(transcript.sentences)

        # ── Step 2: LLM call for deeper analysis ──────────────
        prompt = build_sentiment_prompt(transcript)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise sentiment analyst. Always respond with valid JSON only."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=400,
            temperature=0.1
        )

        # ── Step 3: Parse response ─────────────────────────────
        raw_response = response.choices[0].message.content.strip()

        # Strip markdown code blocks if present
        if raw_response.startswith("```"):
            raw_response = raw_response.split("```")[1]
            if raw_response.startswith("json"):
                raw_response = raw_response[4:]
        raw_response = raw_response.strip()

        data = json.loads(raw_response)

        # ── Step 4: Validate overall_sentiment field ──────────
        valid_sentiments = ["positive", "negative", "neutral"]
        overall = data.get("overall_sentiment", "neutral").lower()
        if overall not in valid_sentiments:
            overall = "neutral"

        # ── Step 5: Build Pydantic model ───────────────────────
        # Combine LLM output with pre-computed values
        sentiment_analysis = SentimentAnalysis(
            meeting_id=meeting_id,
            overall_sentiment=SentimentType(overall),
            sentiment_score=sentiment_score,      # From math, not LLM
            frustration_detected=bool(data.get("frustration_detected", False)),
            escalation_risk=bool(data.get("escalation_risk", False)),
            resolution_detected=bool(data.get("resolution_detected", False)),
            sentiment_arc=sentiment_arc,           # From rule-based, not LLM
            key_moments=data.get("key_moments", [])
        )

        # ── Step 6: Save and log ───────────────────────────────
        save_sentiment_analysis(sentiment_analysis)

        log_agent_action(
            meeting_id=meeting_id,
            agent_name="sentiment_agent",
            action="analyze",
            status="success",
            details={
                "overall_sentiment": overall,
                "sentiment_score": sentiment_score,
                "frustration_detected": sentiment_analysis.frustration_detected,
                "escalation_risk": sentiment_analysis.escalation_risk
            }
        )

        return sentiment_analysis

    except json.JSONDecodeError as e:
        log_agent_action(
            meeting_id=meeting_id,
            agent_name="sentiment_agent",
            action="analyze",
            status="failed",
            details={"error": f"JSON parse error: {str(e)}"}
        )
        print(f"  ⚠️  Sentiment JSON error for {meeting_id}: {e}")
        return None

    except Exception as e:
        log_agent_action(
            meeting_id=meeting_id,
            agent_name="sentiment_agent",
            action="analyze",
            status="failed",
            details={"error": str(e)}
        )
        print(f"  ❌ Sentiment failed for {meeting_id}: {e}")
        return None


# ============================================================
# BATCH ANALYSIS
# ============================================================

def analyze_sentiments_batch(
    transcripts: list[ProcessedTranscript],
    limit: int = None
) -> list[SentimentAnalysis]:
    """Runs sentiment analysis on a list of transcripts."""
    targets = transcripts[:limit] if limit else transcripts
    total = len(targets)
    results = []

    print(f"\n💬 Starting sentiment analysis on {total} transcripts...")

    for i, transcript in enumerate(targets, 1):
        print(f"  [{i}/{total}] {transcript.title[:40]}...", end=" ")
        result = analyze_sentiment(transcript)
        if result:
            arc_str = " → ".join(result.sentiment_arc)
            print(f"→ {result.overall_sentiment.value} "
                  f"(score: {result.sentiment_score:+.2f}) "
                  f"arc: [{arc_str}]")
            results.append(result)
        else:
            print("→ FAILED")

    print(f"\n✅ Sentiment analysis complete: {len(results)}/{total} succeeded")

    # Print escalation summary
    escalations = sum(1 for r in results if r.escalation_risk)
    frustrations = sum(1 for r in results if r.frustration_detected)
    print(f"   🚨 Escalation risk: {escalations}/{len(results)}")
    print(f"   😤 Frustration detected: {frustrations}/{len(results)}")

    return results