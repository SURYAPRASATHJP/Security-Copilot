import argparse
import json
import time
from pathlib import Path
from typing import Any

import httpx

from copilot.data_collection.advisory import Advisory
from copilot.settings import get_settings

NVD_CVE_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"

# NVD allows 5 requests per 30 seconds without a key, and 50 with one.
SECONDS_PER_CALL_WITHOUT_KEY = 6.0
SECONDS_PER_CALL_WITH_KEY = 0.6
THROTTLED_BACKOFF_SECONDS = 30.0
THROTTLED_STATUS_CODES = (403, 429, 503)


def cve_ids_in_scope(path: Path) -> list[str]:
    """Return every distinct CVE alias in the scoped advisory file, in a stable order."""
    seen: dict[str, None] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                for cve in Advisory.model_validate_json(line).cve_ids:
                    seen.setdefault(cve, None)
    return sorted(seen)


def cache_path(cve: str, folder: Path) -> Path:
    return folder / f"{cve}.json"


def extract_details(payload: dict[str, Any]) -> dict[str, Any]:
    """Pull the CVSS score, vector and CWE ids out of one NVD response."""
    vulnerabilities = payload.get("vulnerabilities") or []
    if not vulnerabilities:
        return {"cvss_score": None, "cvss_severity": None, "cvss_vector": None, "cwe_ids": []}

    cve = vulnerabilities[0].get("cve", {})
    metrics = cve.get("metrics", {})
    score = severity = vector = None
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        entries = metrics.get(key) or []
        if not entries:
            continue
        data = entries[0].get("cvssData", {})
        score = data.get("baseScore")
        severity = data.get("baseSeverity") or entries[0].get("baseSeverity")
        vector = data.get("vectorString")
        break

    cwe_ids = []
    for weakness in cve.get("weaknesses", []):
        for description in weakness.get("description", []):
            value = description.get("value", "")
            if value.startswith("CWE-") and value not in cwe_ids:
                cwe_ids.append(value)

    return {
        "cvss_score": score,
        "cvss_severity": severity,
        "cvss_vector": vector,
        "cwe_ids": cwe_ids,
    }


def fetch_one(cve: str, client: httpx.Client, api_key: str = "") -> dict[str, Any]:
    headers = {"apiKey": api_key} if api_key else {}
    for attempt in range(3):
        response = client.get(NVD_CVE_URL, params={"cveId": cve}, headers=headers)
        if response.status_code in THROTTLED_STATUS_CODES:
            time.sleep(THROTTLED_BACKOFF_SECONDS * (attempt + 1))
            continue
        response.raise_for_status()
        return response.json()
    response.raise_for_status()
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description="Cache NVD details for every scoped CVE.")
    parser.add_argument("--limit", type=int, default=0, help="stop after this many new fetches")
    args = parser.parse_args()

    settings = get_settings()
    folder = settings.data_dir / "raw" / "nvd"
    folder.mkdir(parents=True, exist_ok=True)

    cves = cve_ids_in_scope(settings.data_dir / "processed" / "scoped_advisories.jsonl")
    pending = [cve for cve in cves if not cache_path(cve, folder).exists()]
    print(f"cves in scope: {len(cves)}, already cached: {len(cves) - len(pending)}")
    if args.limit:
        pending = pending[: args.limit]

    delay = SECONDS_PER_CALL_WITH_KEY if settings.nvd_api_key else SECONDS_PER_CALL_WITHOUT_KEY
    fetched = failed = 0
    with httpx.Client(timeout=60.0) as client:
        for index, cve in enumerate(pending, start=1):
            try:
                payload = fetch_one(cve, client, settings.nvd_api_key)
            except httpx.HTTPError as error:
                failed += 1
                print(f"{cve} failed: {type(error).__name__}")
            else:
                cache_path(cve, folder).write_text(json.dumps(payload), encoding="utf-8")
                fetched += 1
            if index % 50 == 0:
                print(f"{index} of {len(pending)} done")
            if index < len(pending):
                time.sleep(delay)

    print(f"fetched: {fetched}, failed: {failed}, cache: {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
