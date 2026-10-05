import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from copilot.settings import get_settings

DEFAULT_USERS = 20
DEFAULT_SECONDS = 120
DEFAULT_BASE_URL = "http://127.0.0.1:8000"

REQUIREMENTS = "requests==2.27.1\nflask==2.2.2\nurllib3==1.26.4\n"
QUESTIONS = (
    "Which version of requests fixes CVE-2023-32681?",
    "What is a ReDoS?",
    "Which version of flask fixes GHSA-m2qf-hxjv-5gpq?",
    "Why should I pin my dependency versions?",
)


class Result:
    def __init__(self) -> None:
        self.latencies: list[float] = []
        self.errors = 0
        self.statuses: dict[int, int] = {}

    def record(self, seconds: float, status: int) -> None:
        self.latencies.append(seconds)
        self.statuses[status] = self.statuses.get(status, 0) + 1
        if status >= 400:
            self.errors += 1

    def percentile(self, fraction: float) -> float:
        if not self.latencies:
            return 0.0
        ordered = sorted(self.latencies)
        position = min(int(fraction * len(ordered)), len(ordered) - 1)
        return ordered[position]


def llm_calls_so_far(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


async def one_user(
    client: httpx.AsyncClient, deadline: float, endpoint: str, result: Result, index: int
) -> None:
    turn = index
    while time.perf_counter() < deadline:
        payload = (
            {"requirements": REQUIREMENTS}
            if endpoint == "/check-dependencies"
            else {"question": QUESTIONS[turn % len(QUESTIONS)]}
        )
        started = time.perf_counter()
        try:
            response = await client.post(endpoint, json=payload)
            result.record(time.perf_counter() - started, response.status_code)
        except httpx.HTTPError:
            result.record(time.perf_counter() - started, 599)
        turn += 1


async def run_load(base_url: str, users: int, seconds: int, endpoint: str) -> Result:
    """Hold `users` requests in flight for `seconds`, and record what came back."""
    result = Result()
    deadline = time.perf_counter() + seconds
    limits = httpx.Limits(max_connections=users * 2, max_keepalive_connections=users)
    async with httpx.AsyncClient(base_url=base_url, timeout=120.0, limits=limits) as client:
        await asyncio.gather(
            *(one_user(client, deadline, endpoint, result, index) for index in range(users))
        )
    return result


def report(result: Result, seconds: int, users: int, cache_hit_rate: float | None) -> str:
    total = len(result.latencies)
    lines = [
        "| Measure | Value |",
        "| --- | --- |",
        f"| Concurrent users | {users} |",
        f"| Duration | {seconds} s |",
        f"| Requests completed | {total} |",
        f"| Requests per second | {total / seconds:.1f} |",
        f"| Errors | {result.errors} |",
        f"| p50 latency | {result.percentile(0.50):.3f} s |",
        f"| p95 latency | {result.percentile(0.95):.3f} s |",
        f"| p99 latency | {result.percentile(0.99):.3f} s |",
    ]
    if cache_hit_rate is not None:
        lines.append(f"| Cache hit rate | {cache_hit_rate:.1%} |")
    if total:
        mean = statistics.fmean(result.latencies)
        lines.append(f"| Mean latency | {mean:.3f} s |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Put the API under load and report latency.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--users", type=int, default=DEFAULT_USERS)
    parser.add_argument("--seconds", type=int, default=DEFAULT_SECONDS)
    parser.add_argument("--endpoint", default="/check-dependencies")
    args = parser.parse_args()

    log = get_settings().llm_call_log
    before = llm_calls_so_far(log)

    print(f"{args.users} users against {args.endpoint} for {args.seconds}s")
    result = asyncio.run(run_load(args.base_url, args.users, args.seconds, args.endpoint))

    cache_hit_rate = None
    if args.endpoint == "/ask" and result.latencies:
        new_calls = llm_calls_so_far(log) - before
        cache_hit_rate = max(0.0, 1 - new_calls / len(result.latencies))

    print()
    print(report(result, args.seconds, args.users, cache_hit_rate))
    print()
    print("status codes:", dict(sorted(result.statuses.items())))
    return 0 if result.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
