from pathlib import Path
from src.api.main import read_schema_sql


def test_read_schema_sql_returns_string():
    sql = read_schema_sql()
    assert isinstance(sql, str)
    assert len(sql) > 0


def test_read_schema_sql_contains_expected_tables():
    sql = read_schema_sql()
    assert "CREATE TABLE IF NOT EXISTS documents" in sql
    assert "CREATE TABLE IF NOT EXISTS chunks" in sql
    assert "CREATE TABLE IF NOT EXISTS query_logs" in sql
    assert "CREATE TABLE IF NOT EXISTS ingestion_log" in sql


def test_read_schema_sql_contains_vector_extension():
    sql = read_schema_sql()
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
