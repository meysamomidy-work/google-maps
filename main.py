"""
Scrape Google Maps phone/website for dealerships from per-state CSV files.

Usage:
    python main.py -w 0 -W 4   # worker 0 of 4 (0-based worker id)
"""

from __future__ import annotations

import argparse
import gc
import os
import re
import urllib.parse
from pathlib import Path

import pandas as pd
import psutil
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from tqdm import tqdm
from webdriver_manager.chrome import ChromeDriverManager

INPUT_DIR = Path("crawled")
OUTPUT_DIR = Path("crawled_new")
SKIP_FILES = {"all_dealerships.csv"}

GOOGLE_MAPS_URL_COL = "google maps url"
GOOGLE_MAP_PHONE_COL = "Google Map Phone"
GOOGLE_MAP_WEBSITE_COL = "Google Map Website"

WEBSITE_XPATH = '//a[@data-tooltip="Open website"]'
PHONE_XPATH = '//button[@data-tooltip="Copy phone number"]'


def preprocess_dealership_name(name: object) -> str:
    """Normalize dealership names for Google Maps search (e.g. A & M -> A and M)."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    text = str(name).strip()
    # Spaced ampersand: "H & M", "A & M"
    text = re.sub(r"\s*&\s*", " and ", text)
    # Tight ampersand: "J&S", "A&M"
    text = re.sub(r"(\w)&(\w)", r"\1 and \2", text, flags=re.IGNORECASE)
    # Remaining ampersands
    text = text.replace("&", " and ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def format_us_phone(phone: str) -> str:
    """Format phone as (205) 574-2854 when it is a US 10-digit number."""
    if not phone or not str(phone).strip():
        return ""
    raw = str(phone).strip()
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return raw


def preprocess_address(address: object) -> str:
    if address is None or (isinstance(address, float) and pd.isna(address)):
        return ""
    return re.sub(r"\s+", " ", str(address).strip())


def build_google_maps_url(name: object, address: object) -> str:
    """Build Google Maps search URL like file.ipynb, with proper encoding."""
    query = f"{preprocess_dealership_name(name)} {preprocess_address(address)}".strip()
    encoded = urllib.parse.quote(query, safe="")
    return f"https://www.google.com/maps/search/?api=1&query={encoded}"


def get_memory_usage_mb() -> float:
    return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024


def cleanup_memory() -> None:
    gc.collect()


def create_driver() -> webdriver.Chrome:
    chrome_options = Options()
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-plugins")
    chrome_options.add_argument("--memory-pressure-off")
    chrome_options.add_argument("--disable-background-timer-throttling")
    chrome_options.add_argument("--disable-backgrounding-occluded-windows")
    chrome_options.add_argument("--disable-renderer-backgrounding")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options,
    )
    driver.maximize_window()
    return driver


def extract_phone_and_website(driver: webdriver.Chrome) -> tuple[str, str]:
    website = ""
    phone = ""

    try:
        WebDriverWait(driver, 3).until(
            EC.presence_of_element_located((By.XPATH, WEBSITE_XPATH))
        )
        website = driver.find_element(By.XPATH, WEBSITE_XPATH).get_attribute("href") or ""
    except Exception:
        pass

    try:
        WebDriverWait(driver, 2).until(
            EC.presence_of_element_located((By.XPATH, PHONE_XPATH))
        )
        label = driver.find_element(By.XPATH, PHONE_XPATH).get_attribute("aria-label") or ""
        phone = label.replace("Call: ", "").replace("Phone: ", "").strip()
        phone = format_us_phone(phone)
    except Exception:
        pass

    return phone, website


def list_state_files() -> list[Path]:
    files = sorted(
        f
        for f in INPUT_DIR.glob("*.csv")
        if f.is_file() and f.name not in SKIP_FILES
    )
    return files


def states_for_worker(state_files: list[Path], worker_id: int, total_workers: int) -> list[Path]:
    return [f for i, f in enumerate(state_files) if i % total_workers == worker_id]


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def prepare_dataframe(source_path: Path, output_path: Path) -> pd.DataFrame:
    """Load source rows; resume from partial output if present."""
    source = read_csv(source_path)
    if output_path.exists():
        existing = read_csv(output_path)
        if len(existing) == len(source):
            for col in (GOOGLE_MAPS_URL_COL, GOOGLE_MAP_PHONE_COL, GOOGLE_MAP_WEBSITE_COL):
                if col not in existing.columns:
                    existing[col] = ""
            return existing
        print(f"  warning: {output_path.name} row count mismatch; rebuilding from source")

    df = source.copy()
    for col in (GOOGLE_MAP_PHONE_COL, GOOGLE_MAP_WEBSITE_COL):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)

    if GOOGLE_MAPS_URL_COL not in df.columns:
        df[GOOGLE_MAPS_URL_COL] = ""

    for idx in df.index:
        url = df.at[idx, GOOGLE_MAPS_URL_COL]
        if pd.isna(url) or not str(url).strip():
            df.at[idx, GOOGLE_MAPS_URL_COL] = build_google_maps_url(
                df.at[idx, "Name"],
                df.at[idx, "List Address"],
            )
    return df


def row_needs_scrape(row: pd.Series) -> bool:
    """Skip rows already scraped (phone or website found, or retry only empty both)."""
    phone = str(row.get(GOOGLE_MAP_PHONE_COL, "") or "").strip()
    website = str(row.get(GOOGLE_MAP_WEBSITE_COL, "") or "").strip()
    return not phone and not website


def write_output(df: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8")


def process_state(source_path: Path, output_path: Path) -> None:
    state_name = source_path.stem
    df = prepare_dataframe(source_path, output_path)
    print(f"********* {state_name} started ({len(df)} rows) *********")

    driver = create_driver()
    try:
        for idx in tqdm(range(len(df)), desc=state_name):
            row = df.iloc[idx]
            if not row_needs_scrape(row):
                continue

            url = row[GOOGLE_MAPS_URL_COL]
            if not url or (isinstance(url, float) and pd.isna(url)):
                url = build_google_maps_url(row.get("Name"), row.get("List Address"))
                df.at[idx, GOOGLE_MAPS_URL_COL] = url

            phone, website = "", ""
            try:
                driver.get(url)
                phone, website = extract_phone_and_website(driver)
            except Exception as exc:
                print(f"  row {idx}: scrape error: {exc}")

            df.at[idx, GOOGLE_MAP_PHONE_COL] = phone
            df.at[idx, GOOGLE_MAP_WEBSITE_COL] = website
            write_output(df, output_path)

            if (idx + 1) % 10 == 0:
                cleanup_memory()
                print(f"  memory: {get_memory_usage_mb():.1f} MB")
    finally:
        driver.quit()

    print(f"********* {state_name} finished -> {output_path} *********")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape Google Maps data for dealership CSV files by state."
    )
    parser.add_argument(
        "-w",
        "--worker-id",
        type=int,
        required=True,
        help="This worker's id (0-based). States are assigned where index %% total_workers == worker_id.",
    )
    parser.add_argument(
        "-W",
        "--total-workers",
        type=int,
        required=True,
        help="Total number of workers splitting states.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.total_workers < 1:
        raise SystemExit("total-workers (-W) must be at least 1")
    if args.worker_id < 0 or args.worker_id >= args.total_workers:
        raise SystemExit(f"worker-id (-w) must be between 0 and {args.total_workers - 1}")

    if not INPUT_DIR.is_dir():
        raise SystemExit(f"Missing input folder: {INPUT_DIR}")

    state_files = list_state_files()
    if not state_files:
        raise SystemExit(f"No state CSV files found in {INPUT_DIR}")

    my_states = states_for_worker(state_files, args.worker_id, args.total_workers)
    print(
        f"Worker {args.worker_id}/{args.total_workers}: "
        f"{len(my_states)} of {len(state_files)} states"
    )
    for path in my_states:
        print(f"  - {path.stem}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for source_path in my_states:
        output_path = OUTPUT_DIR / source_path.name
        process_state(source_path, output_path)


if __name__ == "__main__":
    main()
