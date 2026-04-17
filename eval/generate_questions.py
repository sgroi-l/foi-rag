#!/usr/bin/env python3
"""
Automatically generates a multi-chunk eval question set using Claude.

For each FOI document with enough chunks, picks a sliding window of 2-4
adjacent chunks and asks Claude to write a question that requires all of them.
The relevant_chunk_ids are known upfront — no retrieval involved.

Saves to eval/question_set_v2.json.
"""

import asyncio
import json
import os
import random
from pathlib import Path

import anthropic
import asyncpg
from dotenv import load_dotenv

load_dotenv()

OUTPUT = Path(__file__).parent / "question_set_v2.json"

# How many questions to generate in total
TARGET = 25

# Min chunks a document must have before we attempt to generate from it
MIN_CHUNKS = 3

client = anthropic.Anthropic()


async def fetch_documents(pool: asyncpg.Pool) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT d.id, d.foi_reference, d.title
        FROM documents d
        WHERE (SELECT COUNT(*) FROM chunks c WHERE c.document_id = d.id) >= $1
        ORDER BY d.foi_reference
        """,
        MIN_CHUNKS,
    )
    return [dict(r) for r in rows]


async def fetch_chunks(pool: asyncpg.Pool, document_id: str) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT id, page_number, chunk_index, content
        FROM chunks
        WHERE document_id = $1
        ORDER BY page_number, chunk_index
        """,
        document_id,
    )
    return [dict(r) for r in rows]


def pick_window(chunks: list[dict]) -> list[dict]:
    """Pick 2-4 adjacent chunks, biased toward the middle of the document."""
    size = random.choice([2, 2, 3, 3, 4])
    size = min(size, len(chunks))
    max_start = len(chunks) - size
    start = random.randint(0, max_start)
    return chunks[start : start + size]


def generate_question(foi_reference: str, title: str, window: list[dict]) -> dict | None:
    chunk_texts = "\n\n---\n\n".join(
        f"[CHUNK {i}]\n{c['content']}" for i, c in enumerate(window)
    )

    prompt = f"""You are building an evaluation dataset for a RAG system over Camden Council FOI documents.

I will show you {len(window)} adjacent chunks from the same document. Do two things:

1. Write ONE question that:
   - Requires information from AT LEAST 2 of the chunks to answer fully
   - Cannot be answered from any single chunk alone
   - Sounds like something a real person would ask Camden Council
   - Is specific enough that there is a clear correct answer

2. For each chunk, decide whether it is NECESSARY to answer the question (true) or not (false).
   A chunk is necessary only if removing it would make the answer incomplete or impossible.
   Boilerplate, contact details, and sign-offs are never necessary.

Document: {title} (FOI reference: {foi_reference})

Chunks:
{chunk_texts}

Respond with JSON only, no explanation:
{{
  "question": "...",
  "expected_answer": "...",
  "necessary_chunks": [true, false, ...]
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    block = response.content[0]
    if block.type != "text":
        return None
    text = block.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None

    necessary = parsed.get("necessary_chunks", [True] * len(window))
    relevant_ids = [str(c["id"]) for c, needed in zip(window, necessary) if needed]

    if len(relevant_ids) < 2:
        return None  # question didn't actually need multiple chunks

    return {
        "question": parsed["question"],
        "source_foi_reference": foi_reference,
        "expected_answer": parsed["expected_answer"],
        "relevant_chunk_ids": relevant_ids,
    }


async def main() -> None:
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])

    existing: list[dict] = []
    if OUTPUT.exists():
        with open(OUTPUT) as f:
            existing = json.load(f)
        print(f"Resuming — {len(existing)} questions already saved.")

    docs = await fetch_documents(pool)
    print(f"{len(docs)} documents with {MIN_CHUNKS}+ chunks available.")

    # Shuffle so we get variety across documents
    random.shuffle(docs)

    questions = list(existing)
    needed = TARGET - len(questions)
    attempts = 0
    max_attempts = needed * 4  # allow some failures

    for doc in docs:
        if len(questions) >= TARGET:
            break
        if attempts >= max_attempts:
            break

        chunks = await fetch_chunks(pool, doc["id"])
        window = pick_window(chunks)

        print(f"  [{len(questions)+1}/{TARGET}] {doc['foi_reference']} — {len(window)} chunks...", end=" ", flush=True)
        attempts += 1

        entry = generate_question(doc["foi_reference"], doc["title"] or "", window)
        if entry is None:
            print("failed to parse response, skipping.")
            continue

        questions.append(entry)
        with open(OUTPUT, "w") as f:
            json.dump(questions, f, indent=2)
        print("saved.")

    await pool.close()
    print(f"\nDone. {len(questions)} questions saved to {OUTPUT}")


if __name__ == "__main__":
    asyncio.run(main())
