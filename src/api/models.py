from datetime import date, datetime
from pydantic import BaseModel


class QueryRequest(BaseModel):
    query: str
    top_k: int = 5
    date_from: date | None = None
    date_to: date | None = None


class CitationItem(BaseModel):
    foi_reference: str
    title: str
    page_number: int
    chunk_id: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationItem]
    query_id: str


class DocumentRecord(BaseModel):
    id: str
    filename: str
    foi_reference: str | None
    date: date | None
    title: str | None
    total_pages: int | None
    indexed_at: datetime | None


class QueryLog(BaseModel):
    id: str
    query: str
    filters: dict | None
    retrieved_chunk_ids: list[str] | None
    prompt_sent: str | None
    response: str | None
    model: str | None
    queried_at: datetime | None
