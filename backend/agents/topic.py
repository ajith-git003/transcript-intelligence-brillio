# backend/agents/topic.py
# ============================================================
# TOPIC DISCOVERY AGENT
# ============================================================
# RESPONSIBILITY:
#   Analyze one transcript and return:
#   - primary_topic: single best label
#   - themes: supporting sub-topics
#   - keywords: important terms
#   - confidence: how sure the LLM is (0.0-1.0)
#   - reasoning: WHY this topic was chosen (explainability)
#
# WHY LLM-BASED AND NOT CLUSTERING?
#   Classic approach = BERTopic or K-means clustering.
#   Problem: needs enough data to form stable clusters,
#   and produces labels like "Topic_3" not "Outage Response".
#   LLM approach: gives human-readable labels immediately,
#   works on 1 transcript or 1000, and explains its reasoning.
#   Tradeoff: costs API calls. We mitigate with truncation.
#
# CALLED BY: pipeline.py
# INPUT: ProcessedTranscript
# OUTPUT: TopicAnalysis (saved to DB)
# ============================================================

import json
from openai import OpenAI
from backend.models import ProcessedTranscript, TopicAnalysis
from backend.database import save_topic_analysis, log_agent_action

# Initialize OpenAI client once at module level
# This is more efficient than creating it on every function call
from dotenv import load_dotenv
load_dotenv()
client = OpenAI()  # Reads OPENAI_API_KEY from environment automatically


# ============================================================
# TOPIC CATEGORIES
# ============================================================
# We define allowed topics upfront for two reasons:
# 1. Consistency — same concept always gets same label
# 2. Constrained generation — LLM picks from our list
#    rather than inventing new labels every time
#
# Derived from scanning the 100 transcript titles we saw.
TOPIC_CATEGORIES = [
    "Outage Response & Incident Management",
    "Customer Support & Troubleshooting",
    "Contract & Renewal Negotiation",
    "Product Feedback & Feature Requests",
    "Compliance & Security Review",
    "Engineering Planning & Sprint",
    "Customer Onboarding & Deployment",
    "Competitive Analysis & Strategy",
    "Financial & Billing Discussion",
    "Executive Business Review",
    "Product Roadmap Review",
    "Performance & Reliability Review",
]


# ============================================================
# PROMPT BUILDER
# ============================================================

def build_topic_prompt(transcript: ProcessedTranscript) -> str:
    """
    Builds the prompt sent to the LLM for topic analysis.
    
    WHY WE TRUNCATE TO 3000 CHARS:
    GPT-4o-mini has a 128k context window, but longer prompts
    cost more tokens. The first 3000 chars of a transcript
    contain enough information to classify the topic accurately.
    We're optimizing for cost without sacrificing quality.
    
    WHY WE INCLUDE THE SUMMARY:
    The pre-existing summary (from summary.json) is a compressed
    version of the full transcript. Including it gives the LLM
    a high-signal overview even when the transcript is long.
    
    WHY WE ASK FOR JSON OUTPUT:
    Structured output means we can parse it reliably.
    Asking for free-form text would require regex parsing — fragile.
    JSON parsing is deterministic and fast.
    """
    # Truncate full text to control token cost
    truncated_text = transcript.full_text[:3000]
    if len(transcript.full_text) > 3000:
        truncated_text += "\n[... transcript truncated for analysis ...]"

    allowed_topics = "\n".join(f"- {t}" for t in TOPIC_CATEGORIES)

    return f"""You are an expert business analyst analyzing enterprise B2B SaaS call transcripts.

MEETING TITLE: {transcript.title}
CALL TYPE: {transcript.call_type.value}
DURATION: {transcript.duration_minutes:.1f} minutes
PARTICIPANTS: {transcript.participant_count} people

PRE-EXISTING SUMMARY:
{transcript.summary}

TRANSCRIPT EXCERPT:
{truncated_text}

ALLOWED TOPIC CATEGORIES:
{allowed_topics}

Analyze this transcript and respond with ONLY a valid JSON object (no markdown, no explanation outside JSON):

{{
    "primary_topic": "<choose the single best matching category from the list above>",
    "themes": ["<2-4 specific sub-themes found in this conversation>"],
    "keywords": ["<5-8 important keywords or phrases from the transcript>"],
    "confidence": <float between 0.0 and 1.0>,
    "reasoning": "<1-2 sentences explaining why you chose this topic>"
}}

Rules:
- primary_topic MUST be exactly one of the allowed categories
- confidence should reflect how clearly the transcript fits the topic
- keywords should be specific terms from the actual conversation
- reasoning must reference specific evidence from the transcript"""


# ============================================================
# MAIN ANALYSIS FUNCTION
# ============================================================

def analyze_topic(transcript: ProcessedTranscript) -> TopicAnalysis | None:
    """
    Runs topic analysis on one transcript using GPT-4o-mini.
    
    FLOW:
    1. Build prompt with transcript content
    2. Call OpenAI API
    3. Parse JSON response
    4. Validate with Pydantic
    5. Save to database
    6. Log to audit trail
    
    Returns None on failure so pipeline can continue.
    
    WHY GPT-4o-mini AND NOT GPT-4o?
    GPT-4o-mini costs ~15x less than GPT-4o.
    For classification + structured output tasks like this,
    mini performs nearly identically to the full model.
    We save the expensive model for complex reasoning tasks.
    """
    meeting_id = transcript.meeting_id

    try:
        # ── Step 1: Build prompt ───────────────────────────────
        prompt = build_topic_prompt(transcript)

        # ── Step 2: Call OpenAI API ────────────────────────────
        # max_tokens=500 is a hard cap — topic analysis
        # never needs more than ~200 tokens of output.
        # This protects our $5 budget from runaway responses.
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise business analyst. Always respond with valid JSON only."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=500,
            temperature=0.1  # Low temperature = more consistent, less creative
                             # We want reliable classification, not creativity
        )

        # ── Step 3: Extract and parse response ────────────────
        raw_response = response.choices[0].message.content.strip()

        # Remove markdown code blocks if LLM added them despite instructions
        # e.g. ```json {...} ``` → {...}
        if raw_response.startswith("```"):
            raw_response = raw_response.split("```")[1]
            if raw_response.startswith("json"):
                raw_response = raw_response[4:]
        raw_response = raw_response.strip()

        # Parse JSON string into Python dict
        data = json.loads(raw_response)

        # ── Step 4: Validate primary_topic is in our list ─────
        # If LLM hallucinated a topic not in our list, use fallback
        if data.get("primary_topic") not in TOPIC_CATEGORIES:
            data["primary_topic"] = TOPIC_CATEGORIES[0]  # Fallback
            data["confidence"] = max(0.0, data.get("confidence", 0.5) - 0.2)

        # ── Step 5: Build Pydantic model ───────────────────────
        topic_analysis = TopicAnalysis(
            meeting_id=meeting_id,
            primary_topic=data["primary_topic"],
            themes=data.get("themes", []),
            keywords=data.get("keywords", []),
            confidence=float(data.get("confidence", 0.7)),
            reasoning=data.get("reasoning", "")
        )

        # ── Step 6: Save to database ───────────────────────────
        save_topic_analysis(topic_analysis)

        # ── Step 7: Log success ────────────────────────────────
        log_agent_action(
            meeting_id=meeting_id,
            agent_name="topic_agent",
            action="analyze",
            status="success",
            details={
                "primary_topic": topic_analysis.primary_topic,
                "confidence": topic_analysis.confidence
            }
        )

        return topic_analysis

    except json.JSONDecodeError as e:
        # LLM returned malformed JSON
        log_agent_action(
            meeting_id=meeting_id,
            agent_name="topic_agent",
            action="analyze",
            status="failed",
            details={"error": f"JSON parse error: {str(e)}"}
        )
        print(f"  ⚠️  Topic JSON parse error for {meeting_id}: {e}")
        return None

    except Exception as e:
        log_agent_action(
            meeting_id=meeting_id,
            agent_name="topic_agent",
            action="analyze",
            status="failed",
            details={"error": str(e)}
        )
        print(f"  ❌ Topic analysis failed for {meeting_id}: {e}")
        return None


# ============================================================
# BATCH ANALYSIS
# ============================================================

def analyze_topics_batch(
    transcripts: list[ProcessedTranscript],
    limit: int = None
) -> list[TopicAnalysis]:
    """
    Runs topic analysis on a list of transcripts.
    
    limit parameter: useful for testing on 5 transcripts
    before running on all 100. Always test small first.
    
    COST ESTIMATE:
    ~300 input tokens + ~150 output tokens per transcript
    × 100 transcripts × $0.00015/1k tokens (gpt-4o-mini)
    ≈ $0.007 total — less than 1 cent for all 100.
    """
    targets = transcripts[:limit] if limit else transcripts
    total = len(targets)
    results = []

    print(f"\n🔍 Starting topic analysis on {total} transcripts...")

    for i, transcript in enumerate(targets, 1):
        print(f"  [{i}/{total}] {transcript.title[:45]}...", end=" ")
        result = analyze_topic(transcript)
        if result:
            print(f"→ {result.primary_topic[:40]} (conf: {result.confidence:.2f})")
            results.append(result)
        else:
            print("→ FAILED")

    print(f"\n✅ Topic analysis complete: {len(results)}/{total} succeeded")
    return results