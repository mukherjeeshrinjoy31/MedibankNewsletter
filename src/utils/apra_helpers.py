import os
import time

import pandas as pd
import requests
import shutil
import warnings

from ..commons.data import HEADERS

warnings.filterwarnings("ignore", category=FutureWarning)

SKIP_SHEETS = {
    "cover", "notes", "explanatory notes", "about this report",
    "glossary", "notes on statistics", "selection",
    "relatedpublications", "contents", "definitions and abbreviations"
}


def extract_sheets_from_excel(filepath: str, title: str) -> tuple[str, int]:
    """Read an Excel file and extract content from valid sheets, skipping noise sheets."""
    content = f"=== {title} ===\n"
    sheets_extracted = 0

    xl = pd.read_excel(filepath, sheet_name=None, nrows=100)

    for sheet_name, df in xl.items():
        if sheet_name.strip().lower() in SKIP_SHEETS:
            continue
        if sheet_name.strip().lower().startswith("graph"):
            continue

        df = df.dropna(how="all")
        df = df.dropna(thresh=len(df.columns) // 2)
        df = df.astype(object).fillna("")

        if df.empty:
            continue

        content += f"--- {sheet_name} ---\n"
        content += df.to_csv(index=False) + "\n\n"
        sheets_extracted += 1

    return content, sheets_extracted


def download_and_extract(xlsx_links, content_start_string, output_dir="data/apra"):
    """Download XLSX files, extract readable sheet data, and return combined content string."""
    content = content_start_string
    os.makedirs(output_dir, exist_ok=True)

    for title, href in xlsx_links[:5]:
        filename = href.split("/")[-1]
        print(f"Downloading: {filename}...")
        try:
            r = requests.get(href, headers=HEADERS, timeout=60)
            if r.status_code != 200:
                print(f"✗ Failed: {r.status_code}")
                continue

            filepath = os.path.join(output_dir, filename)
            with open(filepath, "wb") as f:
                f.write(r.content)

            try:
                sheet_content, sheets_extracted = extract_sheets_from_excel(filepath, title)
                content += sheet_content
                print(f"✓ {filename} — {sheets_extracted} sheets extracted")

            except Exception as e:
                print(f"✗ Excel read error: {type(e).__name__}: {e}")
                content += f"=== {title} ===\nDownloaded but could not extract text. Error: {e}\nURL: {href}\n\n"

        except Exception as e:
            print(f"✗ Error: {e}")

        time.sleep(1)
    shutil.rmtree(output_dir)
    print(f"Deleted folder: {output_dir}")
    return content