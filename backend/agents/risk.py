# backend/agents/risk.py
# ============================================================
# CHURN RISK AGENT
# ============================================================
# RESPONSIBILITY:
#   Analyze external/support transcripts for churn signals:
#   - Competitor mentions ("we're evaluating CrowdStrike")
#   - Pricing objections ("too expensive", "budget concerns")
#   - Dissatisfaction signals ("considering alternatives")
#   - Contract risk ("not sure about renewal")
#
#   Produces a 0-100 risk score + LOW/MEDIUM/HIGH label
#   with CITATIONS — exact sentences as evidence.
#
# WHY CITATIONS MATTER FOR ENTERPRISE SECURITY:
#   AegisCloud is a security company. Their customers are
#   enterprises with security-conscious procurement teams.
#   "Your AI flagged us as churn risk" needs to be backed
#   by specific evidence a human can verify.
#   Citations = explainability = trust.
#
# INTERNAL CALLS: Skipped (risk_score=0, risk_level=LOW)
#   Churn risk only applies to customer-facing calls.
#
# CALLED BY: pipeline.py
# INPUT: ProcessedTranscript
# OUTPUT: RiskAnalysis (saved to DB)
# ============================================================

import json
from openai import OpenAI
from backend.models import (
    ProcessedTranscript,
    RiskAnalysis,
    RiskLevel,
    CallType
)
from backend.database import save_risk_analysis, log_agent_action
from dotenv import load_dotenv
load_dotenv()

client = OpenAI()


# ============================================================
# COMPETITOR LIST
# ============================================================
# Known competitors in the cybersecurity/backup/compliance space.
# Rule-based check BEFORE the LLM call.
# If we find a competitor mention, we already know risk is elevated.
# This is cheap (string matching) and fast.

COMPETITORS = [
    "crowdstrike", "sentinelone", "defender", "microsoft defender",
    "palo alto", "cortex", "darktrace", "cylance", "carbon black",
    "trend micro", "symantec", "mcafee", "sophos", "veeam",
    "cohesity", "commvault", "veritas", "rubrik",
    "zscaler", "okta", "ping identity", "cyberark"
]

CHURN_KEYWORDS = [
    "cancel", "cancellation", "terminate", "termination",
    "switch", "switching", "replace", "replacement",
    "competitor", "alternative", "evaluate", "evaluation",
    "not renewing", "won't renew", "considering leaving",
    "too expensive", "budget", "cost concern", "pricing issue",
    "disappointed", "frustrated", "unhappy", "dissatisfied",
    "not meeting expectations", "falling short", "promised",
    "contractual", "sla breach", "breach of contract"
]


# ============================================================
# PRE-COMPUTATION (Rule-based, no LLM)
# ============================================================

def detect_competitor_mentions(full_text: str) -> list[str]:
    """
    Scans transcript text for competitor name mentions.
    Case-insensitive string matching — fast and free.
    Returns list of competitor names found.
    """
    text_lower = full_text.lower()
    found = []
    for competitor in COMPETITORS:
        if competitor in text_lower:
            found.append(competitor)
    return found


def detect_churn_keywords(full_text: str) -> list[str]:
    """
    Scans for churn-signal keywords.
    Returns list of keywords found in the transcript.
    """
    text_lower = full_text.lower()
    found = []
    for keyword in CHURN_KEYWORDS:
        if keyword in text_lower:
            found.append(keyword)
    return found


def compute_base_risk_score(
    competitor_mentions: list[str],
    churn_keywords: list[str],
    sentiment_score: float = 0.0
) -> float:
    """
    Computes a base risk score from rule-based signals.
    
    SCORING LOGIC:
    - Each competitor mention: +25 points (very strong signal)
    - Each churn keyword: +8 points
    - Negative sentiment score: up to +15 points
    - Maximum from rules alone: capped at 85
      (LLM can push to 100 with additional context)
    
    WHY THIS WEIGHTING:
    A customer saying "CrowdStrike" once is a much stronger
    churn signal than saying "budget" once.
    Competitor evaluation = active shopping = high risk.
    """
    score = 0.0

    # Competitor mentions are the strongest signal
    score += len(competitor_mentions) * 25

    # Churn keywords add moderate risk
    score += len(churn_keywords) * 8

    # Negative sentiment adds to risk
    # sentiment_score is -1.0 to +1.0
    # We convert negative values to risk points (max +15)
    if sentiment_score < 0:
        score += abs(sentiment_score) * 15

    return min(score, 85.0)  # Cap rule-based at 85


# ============================================================
# PROMPT BUILDER
# ============================================================

def build_risk_prompt(
    transcript: ProcessedTranscript,
    competitor_mentions: list[str],
    churn_keywords: list[str],
    base_score: float
) -> str:
    """
    Sends pre-computed signals to LLM for final assessment.
    
    WHY SEND PRE-COMPUTED SIGNALS TO THE LLM:
    The LLM doesn't need to re-scan for competitors — we did that.
    Instead, we tell it what we found and ask it to:
    1. Assess the severity in context
    2. Find the specific citation sentences
    3. Identify any risk signals our keywords missed
    4. Provide final risk score adjustment
    
    This is called "LLM as reasoner, not scanner" — 
    use the LLM for judgment, rules for detection.
    """
    # Get negative sentences as they're most likely to contain risk signals
    negative_sentences = [
        s for s in transcript.sentences
        if s.sentiment_type == "negative"
    ][:20]

    negative_text = "\n".join([
        f"- {s.speaker_name}: {s.sentence}"
        for s in negative_sentences
    ])

    return f"""You are a B2B SaaS customer success expert specializing in churn risk assessment.

MEETING: {transcript.title}
CALL TYPE: {transcript.call_type.value}
DURATION: {transcript.duration_minutes:.1f} minutes

PRE-ANALYSIS FINDINGS:
- Competitor mentions detected: {competitor_mentions if competitor_mentions else 'None'}
- Churn-signal keywords found: {churn_keywords[:5] if churn_keywords else 'None'}
- Rule-based risk score: {base_score:.0f}/100

SUMMARY:
{transcript.summary}

NEGATIVE/CONCERNING SENTENCES FROM TRANSCRIPT:
{negative_text if negative_text else 'None detected'}

Assess the churn risk and respond with ONLY valid JSON:

{{
    "risk_score": <final score 0-100, consider the pre-analysis findings>,
    "risk_level": "<low|medium|high>",
    "churn_indicators": [
        "<specific risk indicator found in this call>",
        "<another indicator if present>"
    ],
    "pricing_objections": <true|false>,
    "citations": [
        "<exact quote from transcript that indicates risk>",
        "<another exact quote if present, max 3 total>"
    ],
    "confidence": <0.0-1.0, how confident you are in this assessment>,
    "reasoning": "<1-2 sentences explaining the risk assessment>"
}}

Risk level guidelines:
- low (0-30): No significant churn signals, customer appears satisfied
- medium (31-65): Some concerns raised, needs monitoring  
- high (66-100): Active churn risk, immediate action required

For citations: use EXACT short quotes from the transcript.
If no risk signals found, return risk_score: 5, risk_level: low."""


# ============================================================
# MAIN ANALYSIS FUNCTION
# ============================================================

def analyze_risk(transcript: ProcessedTranscript) -> RiskAnalysis | None:
    """
    Runs churn risk analysis on one transcript.
    
    SKIP LOGIC:
    Internal calls (all @aegiscloud.com participants) have no
    churn risk by definition — they're internal meetings.
    We return a minimal LOW risk record rather than skipping
    entirely, so the database has complete coverage.
    """
    meeting_id = transcript.meeting_id

    # ── Skip internal calls ────────────────────────────────────
    if transcript.call_type == CallType.INTERNAL:
        risk_analysis = RiskAnalysis(
            meeting_id=meeting_id,
            risk_level=RiskLevel.LOW,
            risk_score=0.0,
            churn_indicators=[],
            competitor_mentions=[],
            pricing_objections=False,
            citations=[],
            confidence=1.0
        )
        save_risk_analysis(risk_analysis)
        log_agent_action(
            meeting_id=meeting_id,
            agent_name="risk_agent",
            action="analyze",
            status="skipped",
            details={"reason": "Internal call — no churn risk applicable"}
        )
        return risk_analysis

    try:
        # ── Step 1: Rule-based pre-scan ────────────────────────
        competitor_mentions = detect_competitor_mentions(transcript.full_text)
        churn_keywords = detect_churn_keywords(transcript.full_text)

        # Get sentiment score from pre-computed counts
        total = transcript.total_sentences
        if total > 0:
            sentiment_score = (
                transcript.positive_sentence_count -
                transcript.negative_sentence_count
            ) / total
        else:
            sentiment_score = 0.0

        base_score = compute_base_risk_score(
            competitor_mentions,
            churn_keywords,
            sentiment_score
        )

        # ── Step 2: LLM for final judgment ────────────────────
        prompt = build_risk_prompt(
            transcript,
            competitor_mentions,
            churn_keywords,
            base_score
        )

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise churn risk analyst. Always respond with valid JSON only."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=500,
            temperature=0.1
        )

        # ── Step 3: Parse response ─────────────────────────────
        raw_response = response.choices[0].message.content.strip()
        if raw_response.startswith("```"):
            raw_response = raw_response.split("```")[1]
            if raw_response.startswith("json"):
                raw_response = raw_response[4:]
        raw_response = raw_response.strip()

        data = json.loads(raw_response)

        # ── Step 4: Map risk level string to enum ─────────────
        risk_level_map = {
            "low": RiskLevel.LOW,
            "medium": RiskLevel.MEDIUM,
            "high": RiskLevel.HIGH
        }
        risk_level_str = data.get("risk_level", "low").lower()
        risk_level = risk_level_map.get(risk_level_str, RiskLevel.LOW)

        # ── Step 5: Build model ────────────────────────────────
        risk_analysis = RiskAnalysis(
            meeting_id=meeting_id,
            risk_level=risk_level,
            risk_score=float(data.get("risk_score", base_score)),
            churn_indicators=data.get("churn_indicators", []),
            competitor_mentions=competitor_mentions,
            pricing_objections=bool(data.get("pricing_objections", False)),
            citations=data.get("citations", []),
            confidence=float(data.get("confidence", 0.7))
        )

        # ── Step 6: Save and log ───────────────────────────────
        save_risk_analysis(risk_analysis)

        log_agent_action(
            meeting_id=meeting_id,
            agent_name="risk_agent",
            action="analyze",
            status="success",
            details={
                "risk_level": risk_level.value,
                "risk_score": risk_analysis.risk_score,
                "competitor_mentions": competitor_mentions,
                "pricing_objections": risk_analysis.pricing_objections
            }
        )

        return risk_analysis

    except json.JSONDecodeError as e:
        log_agent_action(
            meeting_id=meeting_id,
            agent_name="risk_agent",
            action="analyze",
            status="failed",
            details={"error": f"JSON parse error: {str(e)}"}
        )
        print(f"  ⚠️  Risk JSON error for {meeting_id}: {e}")
        return None

    except Exception as e:
        log_agent_action(
            meeting_id=meeting_id,
            agent_name="risk_agent",
            action="analyze",
            status="failed",
            details={"error": str(e)}
        )
        print(f"  ❌ Risk analysis failed for {meeting_id}: {e}")
        return None


# ============================================================
# BATCH ANALYSIS
# ============================================================

def analyze_risks_batch(
    transcripts: list[ProcessedTranscript],
    limit: int = None
) -> list[RiskAnalysis]:
    """Runs risk analysis on a list of transcripts."""
    targets = transcripts[:limit] if limit else transcripts
    total = len(targets)
    results = []

    print(f"\n⚠️  Starting risk analysis on {total} transcripts...")

    for i, transcript in enumerate(targets, 1):
        print(f"  [{i}/{total}] {transcript.title[:40]}...", end=" ")
        result = analyze_risk(transcript)
        if result:
            flag = "🔴" if result.risk_level == RiskLevel.HIGH else \
                   "🟡" if result.risk_level == RiskLevel.MEDIUM else "🟢"
            print(f"→ {flag} {result.risk_level.value} "
                  f"(score: {result.risk_score:.0f}) "
                  f"competitors: {result.competitor_mentions or 'none'}")
            results.append(result)
        else:
            print("→ FAILED")

    # Summary
    high = sum(1 for r in results if r.risk_level == RiskLevel.HIGH)
    medium = sum(1 for r in results if r.risk_level == RiskLevel.MEDIUM)
    low = sum(1 for r in results if r.risk_level == RiskLevel.LOW)

    print(f"\n✅ Risk analysis complete: {len(results)}/{total}")
    print(f"   🔴 High:   {high}")
    print(f"   🟡 Medium: {medium}")
    print(f"   🟢 Low:    {low}")

    return results