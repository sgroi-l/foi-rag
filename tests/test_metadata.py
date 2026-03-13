import pytest
from datetime import date
from pathlib import Path
from src.ingestion.metadata import load_metadata


def write_csv(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "metadata.csv"
    p.write_text(content, encoding="utf-8-sig")
    return p


def test_load_metadata_basic(tmp_path):
    csv = write_csv(tmp_path, (
        "saved_filename,Identifier,Document Date,Document Title,Document Text\n"
        "01_CAM6551_housing.pdf,CAM6551,2023-12-20T00:00:00.000,housing policy,Some response text\n"
    ))
    result = load_metadata(csv)
    assert "01_CAM6551_housing.pdf" in result
    row = result["01_CAM6551_housing.pdf"]
    assert row.foi_reference == "CAM6551"
    assert row.date == date(2023, 12, 20)
    assert row.title == "housing policy"
    assert row.response_text == "Some response text"


def test_load_metadata_multiple_rows(tmp_path):
    csv = write_csv(tmp_path, (
        "saved_filename,Identifier,Document Date,Document Title,Document Text\n"
        "01_CAM001_a.pdf,CAM001,2023-01-01T00:00:00.000,title a,text a\n"
        "02_CAM002_b.pdf,CAM002,2023-06-15T00:00:00.000,title b,text b\n"
    ))
    result = load_metadata(csv)
    assert len(result) == 2
    assert result["01_CAM001_a.pdf"].foi_reference == "CAM001"
    assert result["02_CAM002_b.pdf"].foi_reference == "CAM002"


def test_load_metadata_invalid_date_becomes_none(tmp_path):
    csv = write_csv(tmp_path, (
        "saved_filename,Identifier,Document Date,Document Title,Document Text\n"
        "01_CAM001_a.pdf,CAM001,not-a-date,title,text\n"
    ))
    result = load_metadata(csv)
    assert result["01_CAM001_a.pdf"].date is None


def test_load_metadata_empty_date_becomes_none(tmp_path):
    csv = write_csv(tmp_path, (
        "saved_filename,Identifier,Document Date,Document Title,Document Text\n"
        "01_CAM001_a.pdf,CAM001,,title,text\n"
    ))
    result = load_metadata(csv)
    assert result["01_CAM001_a.pdf"].date is None


def test_load_metadata_strips_whitespace(tmp_path):
    csv = write_csv(tmp_path, (
        "saved_filename,Identifier,Document Date,Document Title,Document Text\n"
        "01_CAM001_a.pdf,  CAM001  ,2023-01-01T00:00:00.000,  title with spaces  ,  text  \n"
    ))
    result = load_metadata(csv)
    row = result["01_CAM001_a.pdf"]
    assert row.foi_reference == "CAM001"
    assert row.title == "title with spaces"
    assert row.response_text == "text"
