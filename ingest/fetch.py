"""Download PMC Open Access articles (JATS XML + metadata) from the AWS S3 bucket.

Reads the frozen PMCID list produced by the eSearch query in configs/corpus.yaml,
stores one XML and one JSON per article in data/raw/, and records article-level
metadata in SQLite.

Only .xml and .json objects are pulled. Each article also ships a PDF (~10 MB) and
figure images; downloading those would cost several GB and nothing downstream reads
them, since chunking runs on the XML section structure.

Re-runs are cheap: articles already on disk are skipped unless --force is passed.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import boto3
from botocore import UNSIGNED
from botocore.client import Config

BUCKET = "pmc-oa-opendata"
ROOT = Path(__file__).resolve().parent.parent
ID_LIST = ROOT / "configs" / "pmcid_list.json"
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "corpus.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    pmcid        TEXT PRIMARY KEY,
    version      INTEGER,
    pmid         INTEGER,
    doi          TEXT,
    title        TEXT,
    citation     TEXT,
    license_code TEXT,
    is_retracted INTEGER,
    xml_path     TEXT,
    fetched_at   TEXT
);
"""

_local = threading.local()


def s3_client():
    """One boto3 client per thread; clients are not safe to share across threads."""
    if not hasattr(_local, "client"):
        _local.client = boto3.client("s3", config=Config(signature_version=UNSIGNED))
    return _local.client


def latest_version(pmcid: str) -> str | None:
    """Return the highest-numbered version prefix, e.g. 'PMC13417500.2/'."""
    resp = s3_client().list_objects_v2(Bucket=BUCKET, Prefix=f"{pmcid}.", Delimiter="/")
    prefixes = [p["Prefix"] for p in resp.get("CommonPrefixes", [])]
    if not prefixes:
        return None
    # Sort numerically: string sort would rank PMC123.2 above PMC123.10.
    return max(prefixes, key=lambda p: int(p.rstrip("/").rsplit(".", 1)[1]))


def fetch_article(pmcid: str, force: bool = False) -> tuple[str, dict | None]:
    xml_path = RAW_DIR / f"{pmcid}.xml"
    json_path = RAW_DIR / f"{pmcid}.json"

    if not force and xml_path.exists() and json_path.exists():
        return "cached", json.loads(json_path.read_text())

    prefix = latest_version(pmcid)
    if prefix is None:
        return "missing", None

    stem = prefix.rstrip("/")
    client = s3_client()
    meta = json.loads(client.get_object(Bucket=BUCKET, Key=f"{prefix}{stem}.json")["Body"].read())
    xml = client.get_object(Bucket=BUCKET, Key=f"{prefix}{stem}.xml")["Body"].read()

    xml_path.write_bytes(xml)
    json_path.write_text(json.dumps(meta, indent=1))
    return "fetched", meta


def record(conn: sqlite3.Connection, meta: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO articles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            meta["pmcid"],
            meta.get("version"),
            meta.get("pmid"),
            meta.get("doi"),
            meta.get("title"),
            meta.get("citation"),
            meta.get("license_code"),
            int(bool(meta.get("is_retracted"))),
            str((RAW_DIR / f"{meta['pmcid']}.xml").relative_to(ROOT)),
            datetime.now(UTC).isoformat(timespec="seconds"),
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch PMC OA articles.")
    parser.add_argument("--limit", type=int, help="fetch only the first N ids (smoke test)")
    parser.add_argument("--force", action="store_true", help="re-download cached articles")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    pmcids = json.loads(ID_LIST.read_text())
    if args.limit:
        pmcids = pmcids[: args.limit]

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    counts = {"fetched": 0, "cached": 0, "missing": 0, "error": 0}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch_article, p, args.force): p for p in pmcids}
        for i, fut in enumerate(as_completed(futures), start=1):
            pmcid = futures[fut]
            try:
                status, meta = fut.result()
            except Exception as exc:
                print(f"  ERROR {pmcid}: {exc}")
                counts["error"] += 1
                continue
            counts[status] += 1
            if meta is not None:
                record(conn, meta)
            else:
                print(f"  MISSING {pmcid}")
            if i % 25 == 0:
                print(f"  {i}/{len(pmcids)}")

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    retracted = conn.execute("SELECT COUNT(*) FROM articles WHERE is_retracted = 1").fetchone()[0]
    conn.close()

    mb = sum(f.stat().st_size for f in RAW_DIR.glob("*.xml")) / 1e6
    print(f"\n{counts}")
    print(f"articles in db: {total}  |  retracted: {retracted}  |  xml on disk: {mb:.0f} MB")


if __name__ == "__main__":
    main()
