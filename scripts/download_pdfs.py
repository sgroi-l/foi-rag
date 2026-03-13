import re
import time
import random
from pathlib import Path
from urllib.parse import urlparse
from io import StringIO

import pandas as pd
import requests


DATA_URL = "https://opendata.camden.gov.uk/resource/fkj6-gqb4.csv?$limit=50000"

OUTPUT_DIR = Path("camden_foi_random_pdfs")
PDF_DIR = OUTPUT_DIR / "pdfs"
METADATA_CSV = OUTPUT_DIR / "downloaded_pdf_metadata.csv"

N_SAMPLE = 40
RANDOM_SEED = 42
REQUEST_TIMEOUT = 60
SLEEP_BETWEEN_DOWNLOADS = 0.25


def safe_filename(text: str, max_length: int = 150) -> str:
    if pd.isna(text) or not str(text).strip():
        text = "document"
    text = str(text).strip()
    text = re.sub(r'[<>:"/\\|?*]+', "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text[:max_length].rstrip(" .")
    return text or "document"


def looks_like_pdf(url: str) -> bool:
    if not isinstance(url, str) or not url.strip():
        return False
    url_lower = url.lower().strip()
    return ".pdf" in url_lower


def get_extension_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if path.endswith(".pdf"):
        return ".pdf"
    return ".pdf"


def fetch_dataset(url: str) -> pd.DataFrame:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/csv",
    }
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return pd.read_csv(StringIO(response.text))


def standardise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename API columns to the friendly names used in the rest of the script.
    """
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]

    rename_map = {
        "identifier": "Identifier",
        "document_date": "Document Date",
        "document_title": "Document Title",
        "document_text": "Document Text",
        "document_link": "Document Link",
        "last_uploaded": "Last Uploaded",
    }

    df = df.rename(columns=rename_map)
    return df


def download_file(url: str, out_path: Path) -> tuple[bool, str | None, int | None]:
    headers = {
        "User-Agent": "Mozilla/5.0",
    }

    try:
        with requests.get(url, headers=headers, stream=True, timeout=REQUEST_TIMEOUT) as r:
            r.raise_for_status()
            content_type = r.headers.get("Content-Type")
            size_bytes = 0

            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        size_bytes += len(chunk)

        return True, content_type, size_bytes

    except Exception as e:
        return False, str(e), None


def main():
    random.seed(RANDOM_SEED)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    print("Downloading dataset...")
    df = fetch_dataset(DATA_URL)

    print(f"Dataset rows: {len(df):,}")
    print("Columns found:")
    print(list(df.columns))

    df = standardise_columns(df)

    print("Standardised columns:")
    print(list(df.columns))

    required_cols = [
        "Identifier",
        "Document Date",
        "Document Title",
        "Document Text",
        "Document Link",
        "Last Uploaded",
    ]

    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing expected columns after standardising: {missing}")

    pdf_df = df[df["Document Link"].apply(looks_like_pdf)].copy()
    pdf_df = pdf_df.dropna(subset=["Document Link"])
    pdf_df = pdf_df.drop_duplicates(subset=["Document Link"])

    print(f"Rows with PDF links: {len(pdf_df):,}")

    if len(pdf_df) == 0:
        raise ValueError("No PDF links found in the dataset.")

    n_to_sample = min(N_SAMPLE, len(pdf_df))
    sample_df = pdf_df.sample(n=n_to_sample, random_state=RANDOM_SEED).reset_index(drop=True)

    metadata_rows = []

    for i, row in sample_df.iterrows():
        identifier = row.get("Identifier")
        doc_date = row.get("Document Date")
        doc_title = row.get("Document Title")
        doc_text = row.get("Document Text")
        doc_link = row.get("Document Link")
        last_uploaded = row.get("Last Uploaded")

        base_name = safe_filename(f"{i+1:02d}_{identifier}_{doc_title}")
        ext = get_extension_from_url(doc_link)
        out_path = PDF_DIR / f"{base_name}{ext}"

        print(f"[{i+1}/{n_to_sample}] Downloading: {doc_title}")

        success, info, size_bytes = download_file(doc_link, out_path)

        metadata_rows.append({
            "sample_number": i + 1,
            "download_success": success,
            "download_error_or_content_type": info,
            "downloaded_file_size_bytes": size_bytes,
            "saved_filename": out_path.name if success else None,
            "saved_path": str(out_path) if success else None,
            "Identifier": identifier,
            "Document Date": doc_date,
            "Document Title": doc_title,
            "Document Text": doc_text,
            "Document Link": doc_link,
            "Last Uploaded": last_uploaded,
        })

        time.sleep(SLEEP_BETWEEN_DOWNLOADS)

    metadata_df = pd.DataFrame(metadata_rows)
    metadata_df.to_csv(METADATA_CSV, index=False, encoding="utf-8-sig")

    print("\nDone.")
    print(f"PDFs folder: {PDF_DIR.resolve()}")
    print(f"Metadata CSV: {METADATA_CSV.resolve()}")
    print("\nDownload summary:")
    print(metadata_df["download_success"].value_counts(dropna=False))


if __name__ == "__main__":
    main()
