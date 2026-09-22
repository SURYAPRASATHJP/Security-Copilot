import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from copilot.llm_client import ask_llm
from copilot.settings import MissingGroqKeyError, get_settings


def main() -> int:
    try:
        settings = get_settings()
        reply = ask_llm(
            [{"role": "user", "content": "Reply with the two characters OK and nothing else."}],
            prompt_name="check_groq_connection",
            use_cache=False,
        )
    except MissingGroqKeyError as error:
        print(error)
        return 1

    print(reply.strip())
    print(f"model: {settings.model_name}")
    return 0 if reply.strip().upper().startswith("OK") else 1


if __name__ == "__main__":
    raise SystemExit(main())
