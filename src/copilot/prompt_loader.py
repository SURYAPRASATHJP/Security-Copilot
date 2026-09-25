from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"
HEADER_SEPARATOR = "---"


def prompt_path(name: str) -> Path:
    return PROMPTS_DIR / f"{name}.txt"


def split_header(text: str) -> tuple[dict[str, str], str]:
    """Separate a prompt's version header from the template the model actually sees."""
    if HEADER_SEPARATOR not in text:
        return {}, text.strip()

    header_text, _, body = text.partition(f"\n{HEADER_SEPARATOR}\n")
    header = {}
    for line in header_text.splitlines():
        key, separator, value = line.partition(":")
        if separator:
            header[key.strip()] = value.strip()
    return header, body.strip()


@lru_cache
def _read(name: str) -> tuple[dict[str, str], str]:
    return split_header(prompt_path(name).read_text(encoding="utf-8"))


def load_prompt(name: str) -> str:
    """Return a prompt template with its header removed."""
    return _read(name)[1]


def prompt_version(name: str) -> str:
    return _read(name)[0].get("version", "unversioned")
