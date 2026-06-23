# backend/agents/synthesis.py
# ============================================================
# SYNTHESIS (EXECUTIVE SUMMARY) AGENT
# ============================================================
# RESPONSIBILITY:
#   The final agent in the pipeline.
#   Combines outputs from Topic + Sentiment + Risk agents
#   into one leadership-ready ExecutiveSummary per transcript.
#
# WHY A SEPARATE SYNTHESIS AGENT?
#   Each specialist agent sees ONE dimension of the transcript.
#   The synthesis agent sees ALL dimensions together and asks:
#   "Given the topic, sentiment, AND risk — what should
#    leadership know and do about this call?"
#
#   This mirrors how real organizations work:
#   Specialist analysts → Executive briefing
#
# GOVERNANCE FEATURES:
#   - Sets human_review_required flag
#   - Generates recommendations (actionable, not just descriptive)
#   - Creates audit timestamp for every summary
#
# CALLED BY: pipeline.py
# INPUT: ProcessedTranscript + TopicAnalysis + SentimentAnalysis + RiskAnalysis
# OUTPUT: ExecutiveSummary (saved to DB)
# ============================================================

import json
from datetime import datetime, timezone
from dotenv import load_dotenv
from openai import OpenAI
from backend.models import (
    ProcessedTranscript,
    TopicAnalysis,
    SentimentAnalysis,
    RiskAnalysis,
    ExecutiveSummary,
    FeatureRequest,
    RiskLevel,
    CallType
)
from backend.database import save_executive_summary, log_agent_action

load_dotenv()
client = OpenAI()


# ============================================================
# GOVERNANCE LOGIC — Rule-based, no LLM needed
# ============================================================

def should_require_human_review(
    sentiment: SentimentAnalysis,
    risk: RiskAnalysis,
    topic: TopicAnalysis
) -> tuple[bool, str]:
    """
    Determines if a human should review this transcript.
    Rule-based — deterministic and explainable.

    Returns (requires_review: bool, reason: str)

    RULES (any one triggers review):
    1. High churn risk — customer success manager should act
    2. Escalation risk flagged by sentiment agent
    3. Low confidence topic classification — might be miscategorized
    4. Frustration + high risk together — urgent customer situation
    """
    reasons = []

    if risk.risk_level == RiskLevel.HIGH:
        reasons.append(f"High churn risk (score: {risk.risk_score:.0f})")

    if sentiment.escalation_risk:
        reasons.append("Escalation risk detected")

    if topic.confidence < 0.7:
        reasons.append(f"Low topic confidence ({topic.confidence:.2f})")

    if sentiment.frustration_detected and risk.risk_score > 50:
        reasons.append("Frustrated customer with elevated risk")

    if reasons:
        return True, " | ".join(reasons)
    return False, ""


# ============================================================
# PROMPT BUILDER
# ============================================================

def build_synthesis_prompt(
    transcript: ProcessedTranscript,
    topic: TopicAnalysis,
    sentiment: SentimentAnalysis,
    risk: RiskAnalysis
) -> str:
    """
    Sends all agent outputs to LLM for final synthesis.

    WHY WE STILL USE LLM HERE despite having all the data:
    The individual agents produce structured facts.
    The synthesis agent needs to produce NARRATIVE —
    "what does this all mean together?" requires language
    understanding, not just aggregation.

    Example: Topic=Outage + Sentiment=Negative + Risk=High
    A rule can't write: "Northstar Pharma is at immediate
    churn risk following the Detect outage. Their compliance
    team is under pressure and they've mentioned evaluating
    alternatives. Recommend executive outreach within 24hrs."
    Only an LLM can connect those dots into a narrative.
    """
    arc_str = " → ".join(sentiment.sentiment_arc)

    return f"""You are a Chief Customer Officer analyzing a B2B SaaS call for executive briefing.

CALL DETAILS:
- Title: {transcript.title}
- Type: {transcript.call_type.value}
- Duration: {transcript.duration_minutes:.1f} minutes
- Date: {transcript.start_time[:10]}

ANALYSIS RESULTS:
Topic: {topic.primary_topic}
  Themes: {', '.join(topic.themes)}
  Keywords: {', '.join(topic.keywords)}
  Reasoning: {topic.reasoning}

Sentiment: {sentiment.overall_sentiment.value} (score: {sentiment.sentiment_score:+.2f})
  Arc: {arc_str}
  Frustration: {sentiment.frustration_detected}
  Escalation risk: {sentiment.escalation_risk}
  Resolution: {sentiment.resolution_detected}
  Key moments: {sentiment.key_moments[:2]}

Risk: {risk.risk_level.value} (score: {risk.risk_score:.0f}/100)
  Indicators: {risk.churn_indicators[:3]}
  Competitor mentions: {risk.competitor_mentions}
  Pricing objections: {risk.pricing_objections}
  Citations: {risk.citations[:2]}

SUMMARY:
{transcript.summary[:500]}

Generate an executive briefing. Respond with ONLY valid JSON:

{{
    "one_line_summary": "<one crisp sentence a CEO would read — what happened and why it matters>",
    "key_findings": [
        "<finding 1 — specific and actionable>",
        "<finding 2>",
        "<finding 3>",
        "<finding 4 if warranted>"
    ],
    "recommendations": [
        "<recommendation 1 — who should do what by when>",
        "<recommendation 2>",
        "<recommendation 3 if warranted>"
    ],
    "feature_requests": [
        {{
            "feature_description": "<feature request if any found in this call>",
            "business_impact": "<why the customer wants it>"
        }}
    ]
}}

Rules:
- one_line_summary: max 20 words, lead with the business impact
- key_findings: specific facts from THIS call, not generic observations  
- recommendations: include WHO should act (CSM, Engineering, Executive)
- feature_requests: only include if explicitly mentioned in the transcript
- If no feature requests found, return empty array: []"""


# ============================================================
# MAIN SYNTHESIS FUNCTION
# ============================================================

def synthesize(
    transcript: ProcessedTranscript,
    topic: TopicAnalysis,
    sentiment: SentimentAnalysis,
    risk: RiskAnalysis
) -> ExecutiveSummary | None:
    """
    Produces one ExecutiveSummary from all agent outputs.

    This is the last step in the LangGraph pipeline for
    each transcript. After this runs, the transcript is
    fully processed and ready for the API/frontend.
    """
    meeting_id = transcript.meeting_id

    try:
        # ── Step 1: Governance check (rule-based) ─────────────
        needs_review, review_reason = should_require_human_review(
            sentiment, risk, topic
        )

        # ── Step 2: LLM synthesis ──────────────────────────────
        prompt = build_synthesis_prompt(transcript, topic, sentiment, risk)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise executive analyst. Always respond with valid JSON only."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=600,
            temperature=0.2
        )

        # ── Step 3: Parse response ─────────────────────────────
        raw_response = response.choices[0].message.content.strip()
        if raw_response.startswith("```"):
            raw_response = raw_response.split("```")[1]
            if raw_response.startswith("json"):
                raw_response = raw_response[4:]
        raw_response = raw_response.strip()

        data = json.loads(raw_response)

        # ── Step 4: Build feature requests ────────────────────
        feature_requests = []
        for fr in data.get("feature_requests", []):
            if fr.get("feature_description"):
                feature_requests.append(FeatureRequest(
                    feature_description=fr["feature_description"],
                    requester_email=transcript.organizer_email,
                    meeting_id=meeting_id,
                    business_impact=fr.get("business_impact", "")
                ))

        # ── Step 5: Build ExecutiveSummary ─────────────────────
        summary = ExecutiveSummary(
            meeting_id=meeting_id,
            title=transcript.title,
            call_type=transcript.call_type,
            one_line_summary=data.get("one_line_summary", transcript.title),
            key_findings=data.get("key_findings", []),
            recommendations=data.get("recommendations", []),
            topic=topic,
            sentiment=sentiment,
            risk=risk,
            feature_requests=feature_requests,
            human_review_required=needs_review,
            review_reason=review_reason if needs_review else None,
            processed_at=datetime.now(timezone.utc).isoformat()
        )

        # ── Step 6: Save and log ───────────────────────────────
        save_executive_summary(summary)

        log_agent_action(
            meeting_id=meeting_id,
            agent_name="synthesis_agent",
            action="synthesize",
            status="success",
            details={
                "human_review_required": needs_review,
                "feature_requests_found": len(feature_requests),
                "review_reason": review_reason
            }
        )

        return summary

    except json.JSONDecodeError as e:
        log_agent_action(
            meeting_id=meeting_id,
            agent_name="synthesis_agent",
            action="synthesize",
            status="failed",
            details={"error": f"JSON parse error: {str(e)}"}
        )
        print(f"  ⚠️  Synthesis JSON error for {meeting_id}: {e}")
        return None

    except Exception as e:
        log_agent_action(
            meeting_id=meeting_id,
            agent_name="synthesis_agent",
            action="synthesize",
            status="failed",
            details={"error": str(e)}
        )
        print(f"  ❌ Synthesis failed for {meeting_id}: {e}")
        return None


# ============================================================
# BATCH SYNTHESIS
# ============================================================

def synthesize_batch(
    transcripts: list[ProcessedTranscript],
    topics: list[TopicAnalysis],
    sentiments: list[SentimentAnalysis],
    risks: list[RiskAnalysis],
    limit: int = None
) -> list[ExecutiveSummary]:
    """
    Runs synthesis on all transcripts.

    Matches each transcript with its corresponding
    topic/sentiment/risk analysis by meeting_id.
    """
    # Build lookup dicts by meeting_id for O(1) access
    topic_map = {t.meeting_id: t for t in topics}
    sentiment_map = {s.meeting_id: s for s in sentiments}
    risk_map = {r.meeting_id: r for r in risks}

    targets = transcripts[:limit] if limit else transcripts
    total = len(targets)
    results = []
    review_count = 0

    print(f"\n📋 Starting synthesis on {total} transcripts...")

    for i, transcript in enumerate(targets, 1):
        mid = transcript.meeting_id

        # Skip if any agent output is missing
        if mid not in topic_map or mid not in sentiment_map or mid not in risk_map:
            print(f"  [{i}/{total}] SKIP — missing agent output for {mid[:16]}")
            continue

        print(f"  [{i}/{total}] {transcript.title[:45]}...", end=" ")

        result = synthesize(
            transcript,
            topic_map[mid],
            sentiment_map[mid],
            risk_map[mid]
        )

        if result:
            review_flag = "👁️ REVIEW" if result.human_review_required else "✓"
            print(f"→ {review_flag} | {result.one_line_summary[:50]}")
            results.append(result)
            if result.human_review_required:
                review_count += 1
        else:
            print("→ FAILED")

    print(f"\n✅ Synthesis complete: {len(results)}/{total}")
    print(f"   👁️  Flagged for human review: {review_count}")

    return results