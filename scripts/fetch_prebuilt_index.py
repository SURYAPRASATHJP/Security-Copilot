import os
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from copilot.settings import REPO_ROOT, get_settings

INDEX_REPO_ENV = "COPILOT_INDEX_REPO"
INDEX_FILE_ENV = "COPILOT_INDEX_FILE"
DEFAULT_INDEX_FILE = "security-copilot-index.tar.gz"


def index_is_already_here() -> bool:
    settings = get_settings()
    return (settings.data_dir / "processed" / "advisories.jsonl").exists() and (
        settings.chroma_dir
    ).exists()


def download_from_hub(repo_id: str, filename: str) -> Path:
    """Pull the prebuilt corpus and index from a Hugging Face dataset repository."""
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(repo_id=repo_id, filename=filename, repo_type="dataset"))


def unpack(archive: Path, destination: Path) -> None:
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            if not str(target).startswith(str(destination.resolve())):
                raise ValueError(f"refusing to extract {member.name}")
        bundle.extractall(destination)


def main() -> int:
    if index_is_already_here():
        print("the index is already here, nothing to download")
        return 0

    repo_id = os.environ.get(INDEX_REPO_ENV, "").strip()
    if not repo_id:
        print(
            f"no {INDEX_REPO_ENV} is set, so there is no index to fetch. "
            "The dependency check works without one; answering does not."
        )
        return 0

    filename = os.environ.get(INDEX_FILE_ENV, DEFAULT_INDEX_FILE)
    print(f"fetching {filename} from {repo_id}")
    archive = download_from_hub(repo_id, filename)
    unpack(archive, REPO_ROOT)
    print(f"unpacked into {REPO_ROOT}")
    return 0


def pack(destination: Path) -> Path:
    """Build the archive the Space downloads, from a machine that has already built the index."""
    settings = get_settings()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w:gz") as bundle:
        bundle.add(settings.data_dir / "processed", arcname="data/processed")
        bundle.add(settings.data_dir / "eval", arcname="data/eval")
        if settings.chroma_dir.exists():
            bundle.add(settings.chroma_dir, arcname=".chroma")
    return destination


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "pack":
        target = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("dist/index.tar.gz")
        print(f"packed {pack(target)}")
        raise SystemExit(0)
    raise SystemExit(main())
