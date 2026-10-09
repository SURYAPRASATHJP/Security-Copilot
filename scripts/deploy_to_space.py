import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from copilot.settings import REPO_ROOT, get_settings

DEFAULT_SPACE = "security-copilot"
SPACE_SDK = "docker"
INDEX_FILE = "security-copilot-index.tar.gz"

# Everything the Space needs to serve. The corpus and index travel separately.
INCLUDED = (
    "Dockerfile",
    "docker-entrypoint.sh",
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "src",
    "api",
    "app",
    "red_team",
    "scripts",
    "demo_vulnerable_app",
)

SPACE_README = """---
title: Security Copilot
emoji: S
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# Security Copilot

Checks Python dependencies against public advisory databases, explains each finding with a
cited advisory, and proposes a fix. Version ranges are decided by code, never by the model.

This is a public demo. It is rate limited, it works to a daily token budget, and the agent
can only scan the repository built for it. The source is at
https://github.com/SURYAPRASATHJP/security-copilot
"""


def require_token() -> str:
    token = get_settings().hf_token.strip()
    if not token:
        raise SystemExit(
            "HF_TOKEN is not set. Create a write token at huggingface.co/settings/tokens "
            "and paste it into .env after HF_TOKEN=."
        )
    return token


class PaidPlanNeededError(RuntimeError):
    pass


def account(token: str) -> tuple[str, bool]:
    """Return the account name and whether it may create a Docker Space."""
    from huggingface_hub import HfApi

    who = HfApi(token=token).whoami()
    return who["name"], bool(who.get("isPro"))


def require_docker_spaces(is_pro: bool) -> None:
    # Hugging Face made Gradio and Docker Spaces a paid feature, so a free account
    # cannot create one and the request fails well after the upload has started.
    if not is_pro:
        raise PaidPlanNeededError(
            "Creating a Docker Space needs a paid Hugging Face plan and this account is on "
            "the free tier, so the deploy would fail partway. Run the demo locally with "
            "make api and make app instead. See docs/decisions.md."
        )


def create_space(token: str, repo_id: str) -> str:
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(repo_id=repo_id, repo_type="space", space_sdk=SPACE_SDK, exist_ok=True)
    return f"https://huggingface.co/spaces/{repo_id}"


def upload_sources(token: str, repo_id: str) -> int:
    """Push only what the Space needs to serve, not the data or the virtual environment."""
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    readme = REPO_ROOT / "space_readme.md"
    readme.write_text(SPACE_README, encoding="utf-8")

    api.upload_file(
        path_or_fileobj=str(readme),
        path_in_repo="README.md",
        repo_id=repo_id,
        repo_type="space",
    )
    readme.unlink(missing_ok=True)

    uploaded = 1
    for name in INCLUDED:
        if name == "README.md":
            continue
        source = REPO_ROOT / name
        if not source.exists():
            continue
        if source.is_dir():
            api.upload_folder(
                folder_path=str(source),
                path_in_repo=name,
                repo_id=repo_id,
                repo_type="space",
                ignore_patterns=["**/__pycache__/**", "**/.venv/**", "**/*.pyc"],
            )
        else:
            api.upload_file(
                path_or_fileobj=str(source),
                path_in_repo=name,
                repo_id=repo_id,
                repo_type="space",
            )
        uploaded += 1
    return uploaded


def upload_index(token: str, dataset_id: str) -> str:
    """Put the corpus and index in a dataset repository, which the Space fetches at start-up."""
    from huggingface_hub import HfApi

    from scripts.fetch_prebuilt_index import pack

    archive = pack(REPO_ROOT / "dist" / INDEX_FILE)
    api = HfApi(token=token)
    api.create_repo(repo_id=dataset_id, repo_type="dataset", exist_ok=True)
    api.upload_file(
        path_or_fileobj=str(archive),
        path_in_repo=INDEX_FILE,
        repo_id=dataset_id,
        repo_type="dataset",
    )
    return f"https://huggingface.co/datasets/{dataset_id}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy the demo to a Hugging Face Space.")
    parser.add_argument("--space", default=DEFAULT_SPACE)
    parser.add_argument("--skip-index", action="store_true")
    args = parser.parse_args()

    token = require_token()
    owner, is_pro = account(token)
    try:
        require_docker_spaces(is_pro)
    except PaidPlanNeededError as error:
        print(error)
        return 1
    space_id = f"{owner}/{args.space}"
    dataset_id = f"{owner}/{args.space}-index"

    print(f"deploying as {owner}")
    url = create_space(token, space_id)
    print(f"space: {url}")

    uploaded = upload_sources(token, space_id)
    print(f"uploaded {uploaded} paths")

    if not args.skip_index:
        print("packing and uploading the corpus and index")
        print(f"dataset: {upload_index(token, dataset_id)}")

    print()
    print("Two things left, both in the Space settings and both yours to do:")
    print("  1. Add GROQ_API_KEY as a secret.")
    print(f"  2. Add COPILOT_INDEX_REPO as a variable, set to {dataset_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
