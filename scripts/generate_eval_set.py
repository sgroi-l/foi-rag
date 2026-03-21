import asyncio
import json
import os
import random
import sys
from pathlib import Path

import asyncpg
import anthropic
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

N_SAMPLE = 50
# Controls random.sample() — which documents to include.
# Does NOT affect ORDER BY RANDOM() in SQL (which chunk per document).
RANDOM_SEED = 42
OUTPUT_PATH = Path(__file__).parent.parent / "eval" / "question_set.json"

GENERATION_PROMPT = """\
You are generating evaluation data for a RAG system about Camden Council Freedom of Information requests.

Below is an excerpt from an FOI document. Write one specific factual question that this excerpt directly answers, and a concise expected answer based only on this text.

Document: {title} (FOI {foi_reference})
Excerpt:
{content}

Respond in JSON:
{{"question": "...", "expected_answer": "..."}}

Return only the JSON, nothing else."""


def generate_qa(client: anthropic.Anthropic, title: str, foi_reference: str, content: str) -> dict | None:
    """Generate a Q&A pair for a single chunk. Synchronous — called sequentially."""
    prompt = GENERATION_PROMPT.format(title=title, foi_reference=foi_reference, content=content)
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = next(b.text for b in message.content if b.type == "text").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        data = json.loads(text)
        return {
            "question": data["question"],
            "source_foi_reference": foi_reference,
            "source_document_title": title,
            "expected_answer": data["expected_answer"],
        }
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"  Skipping ({foi_reference}): {e}")
        return None


async def main() -> None:
    if OUTPUT_PATH.exists():
        print(f"Output file already exists: {OUTPUT_PATH}")
        print("Delete it first or move it before regenerating.")
        sys.exit(1)

    random.seed(RANDOM_SEED)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    client = anthropic.Anthropic()

    # Fetch one random non-boilerplate chunk per document.
    # Boilerplate (internal review notices, sign-off text) is filtered in SQL
    # so DISTINCT ON only samples from substantive chunks.
    rows = await pool.fetch("""
        SELECT DISTINCT ON (d.id)
            d.foi_reference,
            d.title,
            c.content
        FROM documents d
        JOIN chunks c ON c.document_id = d.id
        WHERE
            lower(c.content) NOT LIKE '%internal review%'
            AND lower(c.content) NOT LIKE '%information rights officer%'
            AND lower(c.content) NOT LIKE '%information commissioner%'
        ORDER BY d.id, RANDOM()
    """)
    await pool.close()

    print(f"Documents available: {len(rows)}")
    sample = random.sample(list(rows), min(N_SAMPLE, len(rows)))
    print(f"Sampling {len(sample)} documents...")

    questions = []
    for i, row in enumerate(sample):
        print(f"[{i + 1}/{len(sample)}] Generating Q&A for: {row['title'] or row['foi_reference']}")
        entry = generate_qa(client, row["title"] or "", row["foi_reference"] or "", row["content"])
        if entry:
            questions.append(entry)

    OUTPUT_PATH.write_text(json.dumps(questions, indent=2, ensure_ascii=False))
    print(f"\nDone. {len(questions)} questions written to {OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
