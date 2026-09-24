import json
from pathlib import Path

from copilot.data_collection.advisory import Advisory
from copilot.data_collection.fetch_exploit_signals import kev_cve_ids
from copilot.data_collection.fetch_nvd_details import extract_details
from copilot.settings import get_settings


def load_nvd_cache(folder: Path) -> dict[str, dict]:
    """Return the extracted NVD details for every CVE already cached on disk."""
    details = {}
    for path in sorted(folder.glob("CVE-*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        details[path.stem] = extract_details(payload)
    return details


def enrich(
    advisory: Advisory,
    nvd: dict[str, dict],
    epss: dict[str, float],
    known_exploited: set[str],
) -> Advisory:
    """Attach the CVSS score, CWEs, exploit probability and KEV flag to one advisory."""
    scores = []
    vectors = []
    cwe_ids: list[str] = []
    probabilities = []

    for cve in advisory.cve_ids:
        details = nvd.get(cve)
        if details:
            if details["cvss_score"] is not None:
                scores.append(details["cvss_score"])
            if details["cvss_vector"]:
                vectors.append(details["cvss_vector"])
            cwe_ids.extend(cwe for cwe in details["cwe_ids"] if cwe not in cwe_ids)
        if cve in epss:
            probabilities.append(epss[cve])

    return advisory.model_copy(
        update={
            "cvss_score": max(scores) if scores else None,
            # OSV carries a vector too, so only overwrite it when NVD has one.
            "cvss_vector": vectors[0] if vectors else advisory.cvss_vector,
            "cwe_ids": cwe_ids,
            "epss_probability": max(probabilities) if probabilities else None,
            "known_exploited": any(cve in known_exploited for cve in advisory.cve_ids),
        }
    )


def read_advisories(path: Path) -> list[Advisory]:
    with path.open(encoding="utf-8") as handle:
        return [Advisory.model_validate_json(line) for line in handle if line.strip()]


def main() -> int:
    settings = get_settings()
    raw = settings.data_dir / "raw"
    processed = settings.data_dir / "processed"

    advisories = read_advisories(processed / "scoped_advisories.jsonl")
    nvd = load_nvd_cache(raw / "nvd")
    epss_path = raw / "epss.json"
    epss = json.loads(epss_path.read_text(encoding="utf-8")) if epss_path.exists() else {}
    kev_path = raw / "kev.json"
    known_exploited = (
        kev_cve_ids(json.loads(kev_path.read_text(encoding="utf-8")))
        if kev_path.exists()
        else set()
    )

    merged = [enrich(advisory, nvd, epss, known_exploited) for advisory in advisories]

    output = processed / "advisories.jsonl"
    with output.open("w", encoding="utf-8") as handle:
        for advisory in merged:
            handle.write(advisory.model_dump_json() + "\n")

    with_cvss = sum(1 for a in merged if a.cvss_score is not None)
    with_epss = sum(1 for a in merged if a.epss_probability is not None)
    with_kev = sum(1 for a in merged if a.known_exploited)
    with_cwe = sum(1 for a in merged if a.cwe_ids)

    print(f"advisories merged: {len(merged)}")
    print(f"nvd responses cached: {len(nvd)}")
    print(f"with a CVSS score: {with_cvss} ({with_cvss / len(merged):.1%})")
    print(f"with a CWE: {with_cwe} ({with_cwe / len(merged):.1%})")
    print(f"with an EPSS probability: {with_epss} ({with_epss / len(merged):.1%})")
    print(f"flagged known exploited: {with_kev}")
    print(f"written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
