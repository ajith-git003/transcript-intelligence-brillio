# backend/retrieval.py
# ============================================================
# VECTOR RETRIEVAL SYSTEM — ChromaDB + OpenAI Embeddings
# ============================================================
# This module provides semantic search over transcripts.
#
# WHY VECTOR SEARCH OVER KEYWORD SEARCH:
#   Keyword: "customer losing access" → matches nothing
#   Vector:  "customer losing access" → matches
#            "complete loss of threat visibility" ✓
#            "zero threat monitoring for 6 hours" ✓
#            "users locked out of the platform" ✓
#
#   Vector search understands MEANING, not just words.
#   This is the difference between a search engine and
#   an intelligence system.
#
# HOW IT WORKS:
#   1. Each transcript's text is converted to a 1536-dim
#      vector using OpenAI text-embedding-3-small
#   2. Vectors stored in ChromaDB (local, no Docker needed)
#   3. At query time: embed the question, find nearest vectors
#      by cosine similarity, retrieve those transcripts
#   4. Pass retrieved transcripts as context to the LLM
#
# THIS IS REAL RAG:
#   Retrieval Augmented Generation =
#   Retrieve relevant docs → Augment the prompt → Generate answer
# ============================================================

import os
import json
import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv
from backend.database import get_connection

load_dotenv()

# ============================================================
# CHROMADB SETUP
# ============================================================

# Persist ChromaDB to disk so embeddings survive restarts
# Without persistence, we'd re-embed everything on each startup
CHROMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "chroma_db"
)

def get_chroma_client():
    """
    Returns a persistent ChromaDB client.
    Data stored at ./chroma_db/ in the project root.
    """
    return chromadb.PersistentClient(path=CHROMA_PATH)


def get_collection():
    """
    Gets or creates the transcript embeddings collection.

    WHY OpenAI embeddings:
    text-embedding-3-small produces 1536-dim vectors.
    It understands enterprise/technical language better
    than sentence-transformers for our use case.
    Cost: ~$0.02 per million tokens — essentially free.
    """
    client = get_chroma_client()

    # Use OpenAI embeddings via ChromaDB's built-in function
    openai_ef = embedding_functions.OpenAIEmbeddingFunction(
        api_key=os.getenv("OPENAI_API_KEY"),
        model_name="text-embedding-3-small"
    )

    collection = client.get_or_create_collection(
        name="transcripts",
        embedding_function=openai_ef,
        metadata={"hnsw:space": "cosine"}  # Cosine similarity for text
    )
    return collection


# ============================================================
# INDEXING — Build the vector store
# ============================================================

def index_transcripts(force_reindex: bool = False) -> int:
    """
    Embeds all transcripts and stores in ChromaDB.

    WHAT GETS EMBEDDED:
    We embed a rich document that combines:
    - Meeting title (most informative)
    - Call type (support/external/internal)
    - Pre-existing summary (compressed meaning)
    - Topic and keywords from our analysis
    - First 1000 chars of full text (actual conversation)

    WHY NOT JUST THE FULL TEXT:
    Embedding 10,000 words would be expensive and noisy.
    The summary + title + topic captures 90% of the meaning
    at 10% of the token cost.

    force_reindex: if True, clears existing embeddings and rebuilds.
    Returns number of documents indexed.
    """
    collection = get_collection()

    # Check if already indexed
    existing_count = collection.count()
    if existing_count > 0 and not force_reindex:
        print(f"✅ Vector store already has {existing_count} documents — skipping indexing")
        return existing_count

    if force_reindex and existing_count > 0:
        print(f"🔄 Force reindexing — clearing {existing_count} existing embeddings...")
        client = get_chroma_client()
        client.delete_collection("transcripts")
        collection = get_collection()

    # Fetch all transcripts with their analysis from SQLite
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            t.meeting_id, t.title, t.call_type, t.summary,
            t.full_text, t.organizer_email,
            ta.primary_topic, ta.keywords, ta.themes,
            sa.overall_sentiment, sa.sentiment_score,
            ra.risk_level, ra.risk_score,
            es.one_line_summary, es.key_findings
        FROM transcripts t
        LEFT JOIN topic_analyses ta ON t.meeting_id = ta.meeting_id
        LEFT JOIN sentiment_analyses sa ON t.meeting_id = sa.meeting_id
        LEFT JOIN risk_analyses ra ON t.meeting_id = ra.meeting_id
        LEFT JOIN executive_summaries es ON t.meeting_id = es.meeting_id
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    if not rows:
        print("❌ No transcripts found in database — run the pipeline first")
        return 0

    print(f"\n🔢 Indexing {len(rows)} transcripts into vector store...")

    # Prepare documents for ChromaDB
    documents = []   # The text we embed
    metadatas = []   # Metadata stored alongside vectors (not embedded)
    ids = []         # Unique identifier for each document

    for row in rows:
        # Parse JSON fields
        keywords = []
        if row.get("keywords"):
            try:
                keywords = json.loads(row["keywords"])
            except Exception:
                pass

        themes = []
        if row.get("themes"):
            try:
                themes = json.loads(row["themes"])
            except Exception:
                pass

        # Build the document to embed
        # This is the text that becomes the vector
        doc_parts = [
            f"Title: {row['title']}",
            f"Call Type: {row['call_type']}",
            f"Topic: {row.get('primary_topic', '')}",
            f"Themes: {', '.join(themes)}",
            f"Keywords: {', '.join(keywords)}",
            f"Sentiment: {row.get('overall_sentiment', '')}",
            f"Risk Level: {row.get('risk_level', '')}",
            f"Summary: {row.get('one_line_summary', '') or row.get('summary', '')}",
            f"Transcript excerpt: {(row.get('full_text') or '')[:800]}"
        ]
        document_text = "\n".join(filter(None, doc_parts))

        # Metadata — stored but NOT embedded
        # Used to filter results and return rich context
        metadata = {
            "meeting_id": row["meeting_id"],
            "title": row["title"],
            "call_type": row["call_type"],
            "primary_topic": row.get("primary_topic", ""),
            "overall_sentiment": row.get("overall_sentiment", ""),
            "risk_level": row.get("risk_level", "low"),
            "risk_score": float(row.get("risk_score") or 0),
            "sentiment_score": float(row.get("sentiment_score") or 0),
            "one_line_summary": row.get("one_line_summary", "")[:200]
        }

        documents.append(document_text)
        metadatas.append(metadata)
        ids.append(row["meeting_id"])

    # Add to ChromaDB in batches of 50
    # (ChromaDB handles embedding API calls internally)
    batch_size = 50
    for i in range(0, len(documents), batch_size):
        batch_docs = documents[i:i+batch_size]
        batch_meta = metadatas[i:i+batch_size]
        batch_ids = ids[i:i+batch_size]

        collection.add(
            documents=batch_docs,
            metadatas=batch_meta,
            ids=batch_ids
        )
        print(f"  Indexed {min(i+batch_size, len(documents))}/{len(documents)}")

    final_count = collection.count()
    print(f"✅ Vector store built: {final_count} documents indexed")
    return final_count


# ============================================================
# SEMANTIC SEARCH
# ============================================================

def semantic_search(
    query: str,
    n_results: int = 5,
    filter_call_type: str = None,
    filter_risk_level: str = None
) -> list[dict]:
    """
    Finds the most semantically relevant transcripts for a query.

    HOW IT WORKS:
    1. ChromaDB embeds the query using the same OpenAI model
    2. Computes cosine similarity between query vector and all stored vectors
    3. Returns the top n_results most similar documents

    COSINE SIMILARITY:
    Two vectors are "similar" if they point in the same direction
    in the 1536-dimensional space. Texts about the same topic
    will have similar vectors even with completely different words.

    Args:
        query: Natural language question from the user
        n_results: How many transcripts to retrieve
        filter_call_type: Optional — only search support/external/internal
        filter_risk_level: Optional — only search high/medium/low risk

    Returns:
        List of dicts with transcript metadata + similarity distance
    """
    collection = get_collection()

    if collection.count() == 0:
        print("⚠️  Vector store empty — run index_transcripts() first")
        return []

    # Build optional metadata filters
    where_filter = None
    if filter_call_type and filter_risk_level:
        where_filter = {
            "$and": [
                {"call_type": {"$eq": filter_call_type}},
                {"risk_level": {"$eq": filter_risk_level}}
            ]
        }
    elif filter_call_type:
        where_filter = {"call_type": {"$eq": filter_call_type}}
    elif filter_risk_level:
        where_filter = {"risk_level": {"$eq": filter_risk_level}}

    # Execute semantic search
    results = collection.query(
        query_texts=[query],   # ChromaDB embeds this automatically
        n_results=min(n_results, collection.count()),
        where=where_filter,
        include=["metadatas", "distances", "documents"]
    )

    # Format results
    formatted = []
    if results and results["metadatas"] and results["metadatas"][0]:
        for i, metadata in enumerate(results["metadatas"][0]):
            result = dict(metadata)
            # Distance is 0-2 for cosine; convert to similarity 0-1
            distance = results["distances"][0][i]
            result["similarity"] = round(1 - (distance / 2), 3)
            result["document_excerpt"] = results["documents"][0][i][:200]
            formatted.append(result)

    return formatted


# ============================================================
# RAG CHAT — Full pipeline
# ============================================================

def rag_answer(
    question: str,
    conversation_history: list[dict] = None,
    n_context_docs: int = 5
) -> dict:
    """
    Full RAG pipeline for the AI chat feature.

    RETRIEVE → AUGMENT → GENERATE

    Step 1 RETRIEVE: semantic_search finds relevant transcripts
    Step 2 AUGMENT: build a prompt with those transcripts as context
    Step 3 GENERATE: GPT-4o-mini answers based only on the context

    WHY THIS IS BETTER THAN JUST ASKING THE LLM:
    Without RAG, the LLM answers from training data — generic,
    hallucinated, not specific to AegisCloud's transcripts.
    With RAG, the LLM can only answer from the actual transcripts
    we retrieved. Every claim is grounded in real data.

    Returns:
        answer: The LLM's response
        sources: List of meeting_ids used as context
        source_titles: Human-readable titles
        retrieved_docs: Full retrieval results for transparency
    """
    from openai import OpenAI
    client = OpenAI()

    # Step 1: RETRIEVE
    relevant_docs = semantic_search(question, n_results=n_context_docs)

    if not relevant_docs:
        # Fallback to database if vector store is empty
        return {
            "answer": "Vector store not yet indexed. Please run indexing first.",
            "sources": [],
            "source_titles": [],
            "retrieved_docs": []
        }

    # Step 2: AUGMENT — build context from retrieved docs
    context_parts = []
    for doc in relevant_docs:
        context_parts.append(
            f"--- Transcript: {doc['title']} ---\n"
            f"Type: {doc['call_type']} | "
            f"Topic: {doc['primary_topic']} | "
            f"Sentiment: {doc['overall_sentiment']} | "
            f"Risk: {doc['risk_level']} (score: {doc['risk_score']})\n"
            f"Summary: {doc['one_line_summary']}\n"
            f"Similarity: {doc['similarity']:.2f}"
        )

    context = "\n\n".join(context_parts)

    # Build messages for multi-turn conversation
    messages = [
        {
            "role": "system",
            "content": """You are an AI analyst for AegisCloud's Transcript Intelligence platform.
You analyze enterprise B2B call transcripts to help product, sales, and engineering leaders.
Answer questions based ONLY on the transcript context provided.
Always cite specific call titles as evidence.
Be specific, actionable, and concise.
If the context doesn't contain enough information, say so."""
        }
    ]

    # Add conversation history (last 4 exchanges for context)
    if conversation_history:
        for msg in conversation_history[-4:]:
            messages.append(msg)

    # Add current question with retrieved context
    messages.append({
        "role": "user",
        "content": f"""Retrieved transcript context (ranked by semantic similarity):

{context}

Question: {question}

Answer based on the transcripts above. Cite specific call titles."""
    })

    # Step 3: GENERATE
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        max_tokens=600,
        temperature=0.2
    )

    answer = response.choices[0].message.content

    return {
        "answer": answer,
        "sources": [doc["meeting_id"] for doc in relevant_docs],
        "source_titles": [doc["title"] for doc in relevant_docs],
        "retrieved_docs": relevant_docs  # Full transparency
    }