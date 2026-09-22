import argparse
import zipfile
from pathlib import Path

import httpx

from copilot.settings import get_settings

OSV_PYPI_ZIP_URL = "https://storage.googleapis.com/osv-vulnerabilities/PyPI/all.zip"


def download_zip(destination: Path, url: str = OSV_PYPI_ZIP_URL) -> Path:
    """Stream the OSV PyPI dump to disk and return where it landed."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=300.0) as response:
        response.raise_for_status()
        with partial.open("wb") as handle:
            for chunk in response.iter_bytes(chunk_size=1 << 20):
                handle.write(chunk)
    partial.replace(destination)
    return destination


def advisory_members(archive: zipfile.ZipFile) -> list[str]:
    """Return the advisory entries in the archive, refusing any that escape the target."""
    safe = []
    for name in archive.namelist():
        if not name.endswith(".json"):
            continue
        if name.startswith("/") or ".." in Path(name).parts:
            raise ValueError(f"refusing to extract {name}")
        safe.append(name)
    return safe


def extract_advisories(archive_path: Path, target: Path) -> int:
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        members = advisory_members(archive)
        archive.extractall(target, members=members)
    return len(members)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download the OSV advisory dump for PyPI.")
    parser.add_argument("--force", action="store_true", help="download again even if cached")
    args = parser.parse_args()

    raw = get_settings().data_dir / "raw"
    archive_path = raw / "osv_pypi.zip"
    target = raw / "osv_pypi"

    if args.force or not archive_path.exists():
        print(f"downloading {OSV_PYPI_ZIP_URL}")
        download_zip(archive_path)
    else:
        print(f"using the cached archive at {archive_path}")

    count = extract_advisories(archive_path, target)
    print(f"advisories: {count}")
    print(f"extracted to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
