import re
from collections.abc import Sequence

from pydantic import BaseModel

from copilot import llm_client
from copilot.settings import get_settings

# Prompt Guard 2 reads at most 512 tokens, so anything longer is checked in windows.
WINDOW_WORDS = 300
WINDOW_OVERLAP_WORDS = 40

UNSAFE_WORDS = ("jailbreak", "injection", "malicious", "unsafe", "attack")
SAFE_WORDS = ("benign", "safe", "no injection")

# A cheap first pass, so an obvious attempt costs nothing and a quiet one still reaches the model.
OBVIOUS_INJECTION = re.compile(
    r"ignore (all |your |the )?(previous |above |prior )?(instructions|rules)"
    r"|disregard (the|your|all) (rules|instructions)"
    r"|system\s*(:|override)"
    r"|you are now (an?|in) \w+"
    r"|developer mode"
    r"|reveal (your|the) (system )?prompt"
    r"|print (your|the) (system )?(prompt|instructions)",
    re.IGNORECASE,
)

DATA_OPENING = "=== BEGIN UNTRUSTED DATA ==="
DATA_CLOSING = "=== END UNTRUSTED DATA ==="


class InputVerdict(BaseModel):
    safe: bool = True
    reason: str = ""
    checked_windows: int = 0
    flagged_window: str = ""

    @property
    def blocked(self) -> bool:
        return not self.safe


def windows(text: str, size: int = WINDOW_WORDS, overlap: int = WINDOW_OVERLAP_WORDS) -> list[str]:
    """Split text into overlapping windows small enough for the guard model to read."""
    words = text.split()
    if not words:
        return []
    if len(words) <= size:
        return [text]

    step = max(1, size - overlap)
    pieces = []
    for start in range(0, len(words), step):
        pieces.append(" ".join(words[start : start + size]))
        if start + size >= len(words):
            break
    return pieces


def looks_like_an_obvious_injection(text: str) -> bool:
    return OBVIOUS_INJECTION.search(text) is not None


def reply_says_unsafe(reply: str) -> bool:
    said = reply.strip().lower()
    if any(word in said for word in SAFE_WORDS):
        return False
    return any(word in said for word in UNSAFE_WORDS) or said.startswith("1")


def ask_the_guard_model(window: str) -> bool:
    settings = get_settings()
    reply = llm_client.ask_llm(
        [{"role": "user", "content": window}],
        prompt_name="input_guard",
        model=settings.guard_model_name,
    )
    return reply_says_unsafe(reply)


def check_input(text: str, use_model: bool = True) -> InputVerdict:
    """Decide whether a piece of input is trying to change the copilot's instructions."""
    pieces = windows(text)
    for piece in pieces:
        if looks_like_an_obvious_injection(piece):
            return InputVerdict(
                safe=False,
                reason="the text tries to override the copilot's instructions",
                checked_windows=len(pieces),
                flagged_window=piece[:200],
            )

    if use_model:
        for piece in pieces:
            try:
                unsafe = ask_the_guard_model(piece)
            except Exception as error:
                return InputVerdict(
                    safe=True,
                    reason=f"the guard model could not be reached: {type(error).__name__}",
                    checked_windows=len(pieces),
                )
            if unsafe:
                return InputVerdict(
                    safe=False,
                    reason=f"{get_settings().guard_model_name} flagged this as an injection",
                    checked_windows=len(pieces),
                    flagged_window=piece[:200],
                )

    return InputVerdict(safe=True, checked_windows=len(pieces))


def wrap_as_data(text: str) -> str:
    """Fence retrieved or scanned text so it reads as data rather than as a brief."""
    return f"{DATA_OPENING}\n{text}\n{DATA_CLOSING}"


def check_retrieved(passages: Sequence[str], use_model: bool = False) -> InputVerdict:
    """Check text that came from an advisory or a repository, not from the user."""
    for passage in passages:
        verdict = check_input(passage, use_model=use_model)
        if verdict.blocked:
            return verdict
    return InputVerdict(safe=True, checked_windows=len(passages))
