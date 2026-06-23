# test_ingestion.py — Full pipeline including synthesis
import os
from dotenv import load_dotenv
from backend.database import init_db
from backend.agents.ingestion import ingest_all_transcripts
from backend.agents.topic import analyze_topics_batch
from backend.agents.sentiment import analyze_sentiments_batch
from backend.agents.risk import analyze_risks_batch
from backend.agents.synthesis import synthesize_batch

load_dotenv()

DATASET_PATH = os.getenv(
    "DATASET_PATH",
    r"D:\Downloads\interview-assignment\interview-assignment\dataset"
)

if __name__ == "__main__":
    init_db()

    transcripts = ingest_all_transcripts(DATASET_PATH)
    topics = analyze_topics_batch(transcripts)
    sentiments = analyze_sentiments_batch(transcripts)
    risks = analyze_risks_batch(transcripts)

    # Full synthesis on all 100
    summaries = synthesize_batch(transcripts, topics, sentiments, risks)

    print("\n" + "="*50)
    print("FULL PIPELINE COMPLETE")
    print("="*50)
    print(f"Transcripts processed:  {len(transcripts)}")
    print(f"Topics classified:      {len(topics)}")
    print(f"Sentiments analyzed:    {len(sentiments)}")
    print(f"Risks scored:           {len(risks)}")
    print(f"Summaries generated:    {len(summaries)}")

    review_needed = [s for s in summaries if s.human_review_required]
    print(f"Human review flagged:   {len(review_needed)}")

    print("\n--- Sample Executive Summary ---")
    if summaries:
        s = summaries[0]
        print(f"Title: {s.title}")
        print(f"Summary: {s.one_line_summary}")
        print(f"Key findings:")
        for f in s.key_findings[:3]:
            print(f"  • {f}")
        print(f"Recommendations:")
        for r in s.recommendations[:2]:
            print(f"  → {r}")
        print(f"Review required: {s.human_review_required}")
        if s.review_reason:
            print(f"Review reason: {s.review_reason}")