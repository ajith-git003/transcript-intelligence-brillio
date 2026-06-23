# Bonus Insights — Beyond the Required Tasks

## What I Built vs What I'd Build Next

The required pipeline (topic classification, sentiment analysis) is
fully implemented and running on all 100 transcripts.

Here are three additional insights I identified, with varying levels
of implementation:

---

## Insight 1: Customer Health Score Timeline
**Status: Designed, not implemented**
**Stakeholder: Customer Success Managers**

### The Insight
Individual call analysis misses the most important signal:
*how is a customer's sentiment trending over time?*

Blackridge Investments appears in 3 transcripts this dataset:
- March: Neutral sentiment, routine check-in
- March (later): Negative, outage impact discussion
- March (urgent): Critical, "evaluating SentinelShield"

The churn signal was visible 2 calls before the crisis.
A CSM reviewing individual calls would miss this pattern.
A timeline view makes it obvious.

### Why It Matters
B2B SaaS churn is rarely sudden. Customers deteriorate over
multiple interactions. Catching the trend at -0.3 sentiment
is dramatically cheaper than recovering at -0.7.

### How to Build It
1. Group transcripts by customer (email domain)
2. Sort by start_time
3. Plot sentiment_score as a timeline per customer
4. Flag customers where trend is declining over 2+ calls
5. Alert CSM when trend crosses threshold

### Data Available
All fields needed already exist in the database:
- organizer_email (domain = customer)
- start_time
- sentiment_score
- overall_sentiment

---

## Insight 2: Feature Request Deduplication and Ranking
**Status: Partially implemented (extraction works, clustering needed)**
**Stakeholder: Product Managers**

### The Insight
The synthesis agent already extracts feature requests per transcript.
The problem: the same feature appears differently across calls.

From the dataset:
- "SCIM 2.0 integration" (Support Case #3546)
- "automated user provisioning" (likely same request)
- "directory sync support" (likely same request)

Without deduplication, Product sees 3 separate requests.
With clustering, they see 1 request with priority 3.

### Why It Matters
Roadmap decisions made from undeduplicated data are wrong.
A feature requested by 1 customer loudly looks the same as
a feature requested quietly by 8 customers.

### How to Build It
1. Embed all feature_description fields using text-embedding-3-small
2. Cluster using ChromaDB (infrastructure already exists)
3. Count transcripts per cluster = demand signal
4. Rank clusters by frequency × customer tier
5. Export as PM-ready priority list

---

## Insight 3: Competitive Intelligence Dashboard
**Status: Data exists, dashboard not built**
**Stakeholder: Sales team, Strategy**

### The Insight
The risk agent already detects competitor mentions and stores them
in the competitor_mentions field. Currently: Okta (4 calls),
SentinelShield (1 call).

But raw counts miss context:
- "We evaluated Okta" in a positive renewal = lost evaluation, won renewal
- "We're evaluating Okta right now" in a frustrated call = active risk

Sentiment-weighted competitive mentions tell a richer story.

### Why It Matters
Sales battlecards built from real customer conversations are
more credible than analyst reports. "Our customers who evaluated
CrowdStrike said X" is a compelling sales tool.

### How to Build It
1. Join competitor_mentions with sentiment_score per transcript
2. Categorize: won (positive sentiment), lost (churned), at-risk
3. Extract the sentences around competitor mentions for context
4. Aggregate by competitor: frequency, win rate, common objections
5. Surface as a competitive intelligence card per competitor

---

## On Dataset Augmentation

The raw dataset had no call_type labels — transcripts were
undifferentiated JSON folders. Rather than treating this as
a limitation, I built a rule-based classifier:

- All @aegiscloud.com emails → Internal
- Title contains "Support Case" → Support  
- Mixed domains → External

This enrichment was necessary for all downstream analysis
(sentiment trends by call type, risk scoring for external calls only).

Result: 42 external, 30 support, 28 internal — a realistic
distribution for a B2B SaaS company.