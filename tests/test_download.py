import pytest
import pandas as pd
from scripts.download_pdfs import safe_filename, looks_like_pdf, standardise_columns


# --- safe_filename ---

def test_safe_filename_normal():
    assert safe_filename("01_CAM6551_housing policy") == "01_CAM6551_housing policy"

def test_safe_filename_removes_illegal_chars():
    result = safe_filename('file<>:"/\\|?*name')
    assert "<" not in result
    assert ">" not in result
    assert ":" not in result
    assert '"' not in result

def test_safe_filename_empty_string():
    assert safe_filename("") == "document"

def test_safe_filename_nan():
    assert safe_filename(float("nan")) == "document"

def test_safe_filename_whitespace_only():
    assert safe_filename("   ") == "document"

def test_safe_filename_truncates_to_max_length():
    long = "a" * 200
    result = safe_filename(long, max_length=150)
    assert len(result) <= 150

def test_safe_filename_strips_trailing_dots():
    result = safe_filename("filename...")
    assert not result.endswith(".")

def test_safe_filename_collapses_whitespace():
    result = safe_filename("too   many    spaces")
    assert "  " not in result


# --- looks_like_pdf ---

def test_looks_like_pdf_true():
    assert looks_like_pdf("https://example.com/file.pdf") is True

def test_looks_like_pdf_uppercase():
    assert looks_like_pdf("https://example.com/file.PDF") is True

def test_looks_like_pdf_pdf_in_query_string():
    assert looks_like_pdf("https://example.com/download?file=report.pdf&token=abc") is True

def test_looks_like_pdf_false_for_docx():
    assert looks_like_pdf("https://example.com/file.docx") is False

def test_looks_like_pdf_false_for_empty():
    assert looks_like_pdf("") is False

def test_looks_like_pdf_false_for_non_string():
    assert looks_like_pdf(None) is False
    assert looks_like_pdf(123) is False


# --- standardise_columns ---

def test_standardise_columns_renames_correctly():
    df = pd.DataFrame(columns=[
        "identifier", "document_date", "document_title",
        "document_text", "document_link", "last_uploaded"
    ])
    result = standardise_columns(df)
    assert "Identifier" in result.columns
    assert "Document Date" in result.columns
    assert "Document Title" in result.columns
    assert "Document Link" in result.columns

def test_standardise_columns_strips_spaces():
    df = pd.DataFrame(columns=["  identifier  ", "document_date"])
    result = standardise_columns(df)
    assert "Identifier" in result.columns

def test_standardise_columns_does_not_modify_original():
    df = pd.DataFrame(columns=["identifier"])
    standardise_columns(df)
    assert "identifier" in df.columns  # original unchanged
