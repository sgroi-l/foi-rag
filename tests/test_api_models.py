from datetime import date
from src.api.models import QueryRequest, QueryResponse, DocumentRecord, QueryLog


def test_query_request_defaults():
    req = QueryRequest(query="test")
    assert req.top_k == 5
    assert req.date_from is None
    assert req.date_to is None


def test_query_request_with_dates():
    req = QueryRequest(query="test", date_from=date(2023, 1, 1), date_to=date(2024, 12, 31))
    assert req.date_from == date(2023, 1, 1)


def test_document_record_fields():
    doc = DocumentRecord(
        id="uuid",
        filename="file.pdf",
        foi_reference="CAM1234",
        date=date(2023, 1, 1),
        title="Test",
        total_pages=3,
        indexed_at="2024-01-15T10:30:00Z",
    )
    assert doc.foi_reference == "CAM1234"


def test_query_log_fields():
    log = QueryLog(
        id="uuid",
        query="test query",
        filters={"date_from": "None"},
        retrieved_chunk_ids=["id1"],
        prompt_sent="...",
        response="answer",
        model="claude-sonnet-4-6",
        queried_at="2024-01-15T10:30:00Z",
    )
    assert log.model == "claude-sonnet-4-6"
