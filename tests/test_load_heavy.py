"""
Demo load test for the open-notebook app — simulates 30 concurrent users.

Each simulated user gets their own session and follows a realistic flow:
  • ALL 30 users: 3 sequential text-search queries (building on context)
  • 10 users (randomly chosen): also start a global-chat session and send 2 turns
  • 10 users (randomly chosen, no overlap): also submit a background research job
    and poll until it completes

Total requests in a typical run:
  30×3 search + 10×(1 session + 2 chat) + 10×(1 submit + N polls) ≈ 130+

Usage:
  python test_load_heavy.py [--users N] [--password SECRET]
                                   [--url URL] [--think SECONDS]

Requirements:
  pip install requests
"""

import argparse
import json
import random
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:5055"
API_PREFIX = "/api"   # all routes are mounted under /api
NUM_USERS = 10   # sane default for a local single-process server; use --users 30 for full load
GLOBAL_CHAT_USERS_RATIO = 1 / 3   # ~10 out of 30 also do global chat
RESEARCH_USERS_RATIO = 1 / 3       # ~10 out of 30 also submit research (disjoint)

TIMEOUT_FAST = 120       # seconds — for search, session creation (generous under load)
TIMEOUT_CHAT = 300       # seconds — for chat turns (LLM calls)
TIMEOUT_POLL = 600       # seconds — research jobs can be slow under load
POLL_INTERVAL = 5        # seconds between research-job status polls

DEFAULT_THINK_TIME = 2.0

# ── Search queries ──────────────────────────────────────────────────────────

SEARCH_SEQUENCES = [
    [
        "What are the main topics in this notebook?",
        "Tell me more about the first concept you found.",
        "Where can I read about that in the source materials?",
    ],
    [
        "How does the theoretical framework apply in practice?",
        "What evidence supports this framework?",
        "Are there any counterarguments?",
    ],
    [
        "What key definitions should I know?",
        "Can you give an example of that definition?",
        "What is the historical background of this concept?",
    ],
    [
        "What are the most important findings in the notes?",
        "How are those findings connected?",
        "What conclusions can be drawn?",
    ],
    [
        "Summarise the sources added to this project.",
        "Which source is most relevant to the main question?",
        "What gaps remain after reading all the sources?",
    ],
    [
        "What practical steps follow from the research?",
        "What are the risks or limitations?",
        "What would you recommend exploring next?",
    ],
]

# ── Global-chat conversation turns ─────────────────────────────────────────

GLOBAL_CHAT_TURNS = [
    [
        "Give me an overview of all the content available.",
        "What are the most important points I should focus on?",
    ],
    [
        "What themes come up repeatedly across the sources?",
        "How do those themes relate to each other?",
    ],
    [
        "Explain the main argument found in the materials.",
        "What evidence supports that argument?",
    ],
    [
        "What questions remain unanswered after reading the sources?",
        "How would you prioritise investigating those questions?",
    ],
    [
        "What is the most surprising thing you found in the content?",
        "How does that connect to the broader context?",
    ],
]

# ── Research queries ────────────────────────────────────────────────────────

RESEARCH_QUERIES = [
    "Provide a comprehensive research report on the main topics in the knowledge base.",
    "What are the latest developments related to the subjects covered in these materials?",
    "Analyse the theoretical foundations found in the sources.",
    "What are the practical implications of the key concepts in the notes?",
    "Write a research summary on the central themes across all content.",
    "Investigate the historical context of the primary subject matter.",
    "What do experts say about the topics covered in these materials?",
    "Provide an evidence-based overview of the main research question.",
    "Summarise the state of the art in the domain covered by these notes.",
    "What open problems exist in the field described by the knowledge base?",
]

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    endpoint: str
    user_id: int
    turn: int           # sequential index (1-based for multi-turn, 0 for single-shot)
    success: bool
    elapsed: float
    status_code: Optional[int] = None
    error: Optional[str] = None
    extra: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        if self.turn:
            return f"user={self.user_id:02d}  /{self.endpoint}  turn={self.turn}"
        return f"user={self.user_id:02d}  /{self.endpoint}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth_headers(password: str, user_id: int) -> dict:
    """
    Authentication header (Bearer password) plus a per-user X-Forwarded-For
    so that rate-limit buckets (if any) are isolated per simulated user.
    """
    return {
        "Authorization": f"Bearer {password}",
        "X-Forwarded-For": f"10.0.{(user_id - 1) // 256}.{(user_id - 1) % 256}",
        "Content-Type": "application/json",
    }


def _think(mean_seconds: float):
    if mean_seconds > 0:
        time.sleep(random.expovariate(1.0 / mean_seconds))


# ---------------------------------------------------------------------------
# Per-request functions
# ---------------------------------------------------------------------------

def _do_search(user_id: int, turn: int, query: str,
               base_url: str, password: str) -> StepResult:
    payload = {
        "query": query,
        "type": "text",
        "limit": 10,
        "search_sources": True,
        "search_notes": True,
    }
    t0 = time.monotonic()
    try:
        resp = requests.post(
            f"{base_url}{API_PREFIX}/search",
            json=payload,
            timeout=TIMEOUT_FAST,
            headers=_auth_headers(password, user_id),
        )
        elapsed = time.monotonic() - t0
        if resp.status_code == 429:
            return StepResult("search", user_id, turn, False, elapsed,
                              resp.status_code, "Rate limited")
        if resp.status_code != 200:
            return StepResult("search", user_id, turn, False, elapsed,
                              resp.status_code, resp.text[:120])
        data = resp.json()
        total = data.get("total_count", 0)
        return StepResult("search", user_id, turn, True, elapsed,
                          resp.status_code, extra={"results": total})
    except Exception as exc:
        return StepResult("search", user_id, turn, False,
                          time.monotonic() - t0, error=str(exc))


def _do_create_global_session(user_id: int,
                               base_url: str, password: str) -> StepResult:
    payload = {"title": f"Load-test session for user {user_id:02d}"}
    t0 = time.monotonic()
    try:
        resp = requests.post(
            f"{base_url}{API_PREFIX}/global-chat/sessions",
            json=payload,
            timeout=TIMEOUT_FAST,
            headers=_auth_headers(password, user_id),
        )
        elapsed = time.monotonic() - t0
        if resp.status_code == 429:
            return StepResult("global-chat/sessions", user_id, 0, False,
                              elapsed, resp.status_code, "Rate limited")
        if resp.status_code not in (200, 201):
            return StepResult("global-chat/sessions", user_id, 0, False,
                              elapsed, resp.status_code, resp.text[:120])
        session_id = resp.json().get("id", "")
        return StepResult("global-chat/sessions", user_id, 0, True, elapsed,
                          resp.status_code, extra={"session_id": session_id})
    except Exception as exc:
        return StepResult("global-chat/sessions", user_id, 0, False,
                          time.monotonic() - t0, error=str(exc))


def _do_global_chat(user_id: int, turn: int, session_id: str, message: str,
                    base_url: str, password: str) -> StepResult:
    payload = {"session_id": session_id, "message": message}
    t0 = time.monotonic()
    try:
        resp = requests.post(
            f"{base_url}{API_PREFIX}/global-chat/execute",
            json=payload,
            timeout=TIMEOUT_CHAT,
            headers=_auth_headers(password, user_id),
        )
        elapsed = time.monotonic() - t0
        if resp.status_code == 429:
            return StepResult("global-chat/execute", user_id, turn, False,
                              elapsed, resp.status_code, "Rate limited")
        if resp.status_code != 200:
            return StepResult("global-chat/execute", user_id, turn, False,
                              elapsed, resp.status_code, resp.text[:120])
        data = resp.json()
        msgs = data.get("messages", [])
        last_answer = msgs[-1].get("content", "") if msgs else ""
        return StepResult("global-chat/execute", user_id, turn, True, elapsed,
                          resp.status_code,
                          extra={"answer_len": len(last_answer),
                                 "msg_count": len(msgs)})
    except Exception as exc:
        return StepResult("global-chat/execute", user_id, turn, False,
                          time.monotonic() - t0, error=str(exc))


def _do_submit_research(user_id: int, query: str,
                         base_url: str, password: str) -> StepResult:
    payload = {
        "query": query,
        "report_type": "research_report",
        "report_source": "web",
        "tone": "Objective",
        "source_urls": [],
        "run_in_background": True,
    }
    t0 = time.monotonic()
    try:
        resp = requests.post(
            f"{base_url}{API_PREFIX}/research/generate",
            json=payload,
            timeout=TIMEOUT_FAST,
            headers=_auth_headers(password, user_id),
        )
        elapsed = time.monotonic() - t0
        if resp.status_code == 429:
            return StepResult("research/generate", user_id, 0, False,
                              elapsed, resp.status_code, "Rate limited")
        if resp.status_code != 200:
            return StepResult("research/generate", user_id, 0, False,
                              elapsed, resp.status_code, resp.text[:120])
        job_id = resp.json().get("job_id", "")
        return StepResult("research/generate", user_id, 0, True, elapsed,
                          resp.status_code, extra={"job_id": job_id})
    except Exception as exc:
        return StepResult("research/generate", user_id, 0, False,
                          time.monotonic() - t0, error=str(exc))


def _do_poll_research(user_id: int, job_id: str,
                       base_url: str, password: str) -> StepResult:
    """Poll GET /research/jobs/{job_id} until status is 'completed' or 'failed'."""
    deadline = time.monotonic() + TIMEOUT_POLL
    t0 = time.monotonic()
    last_status = "unknown"
    try:
        while time.monotonic() < deadline:
            resp = requests.get(
                f"{base_url}{API_PREFIX}/research/jobs/{job_id}",
                timeout=TIMEOUT_FAST,
                headers=_auth_headers(password, user_id),
            )
            if resp.status_code != 200:
                return StepResult("research/jobs/poll", user_id, 0, False,
                                  time.monotonic() - t0, resp.status_code,
                                  resp.text[:120])
            data = resp.json()
            last_status = data.get("status", "unknown")
            if last_status in ("completed", "failed"):
                elapsed = time.monotonic() - t0
                success = last_status == "completed"
                report_len = len(data.get("report", "") or "")
                error = data.get("error") if not success else None
                return StepResult("research/jobs/poll", user_id, 0, success,
                                  elapsed, 200,
                                  error=error,
                                  extra={"final_status": last_status,
                                         "report_len": report_len,
                                         "progress": data.get("progress_pct", 0)})
            time.sleep(POLL_INTERVAL)

        return StepResult("research/jobs/poll", user_id, 0, False,
                          time.monotonic() - t0, None,
                          error=f"Timed out after {TIMEOUT_POLL}s (last status: {last_status})")
    except Exception as exc:
        return StepResult("research/jobs/poll", user_id, 0, False,
                          time.monotonic() - t0, error=str(exc))


# ---------------------------------------------------------------------------
# Simulated user session
# ---------------------------------------------------------------------------

def simulate_user(
    user_id: int,
    base_url: str,
    password: str,
    think_time: float,
    do_global_chat: bool,
    do_research: bool,
    print_lock: threading.Lock,
) -> list[StepResult]:
    """
    Simulate one user's full interaction with open-notebook:
      1. 3 text-search turns
      2. Optionally: global-chat session (create + 2 turns)
      3. Optionally: research job (submit + poll to completion)
    """
    results: list[StepResult] = []
    search_seq = random.choice(SEARCH_SEQUENCES)

    # ── Phase 1: searches ────────────────────────────────────────────────────
    for turn_idx, query in enumerate(search_seq, start=1):
        if turn_idx > 1:
            _think(think_time)
        step = _do_search(user_id, turn_idx, query, base_url, password)
        results.append(step)
        with print_lock:
            _print_step(step)

    # ── Phase 2: global chat ────────────────────────────────────────────────
    if do_global_chat:
        _think(think_time)
        create_step = _do_create_global_session(user_id, base_url, password)
        results.append(create_step)
        with print_lock:
            _print_step(create_step)

        if create_step.success:
            session_id = create_step.extra.get("session_id", "")
            turns = random.choice(GLOBAL_CHAT_TURNS)
            for turn_idx, message in enumerate(turns, start=1):
                _think(think_time)
                step = _do_global_chat(user_id, turn_idx, session_id,
                                       message, base_url, password)
                results.append(step)
                with print_lock:
                    _print_step(step)

    # ── Phase 3: research ────────────────────────────────────────────────────
    if do_research:
        _think(think_time)
        query = RESEARCH_QUERIES[(user_id - 1) % len(RESEARCH_QUERIES)]
        submit_step = _do_submit_research(user_id, query, base_url, password)
        results.append(submit_step)
        with print_lock:
            _print_step(submit_step)

        if submit_step.success:
            job_id = submit_step.extra.get("job_id", "")
            poll_step = _do_poll_research(user_id, job_id, base_url, password)
            results.append(poll_step)
            with print_lock:
                _print_step(poll_step)

    return results


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _print_step(r: StepResult):
    mark = "✓" if r.success else "✗"
    status = "PASS" if r.success else "FAIL"
    print(f"  {mark} [{status}] {r.label}  elapsed={r.elapsed:.2f}s  http={r.status_code}",
          end="")
    if r.extra:
        for k, v in r.extra.items():
            if k != "session_id":    # skip internal ids in live output
                print(f"  {k}={v}", end="")
    print()
    if r.error:
        print(f"       ERROR: {r.error}")
    sys.stdout.flush()


def print_summary(results: list[StepResult], total_elapsed: float, num_users: int):
    passed = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    print("\n" + "=" * 72)
    print(f"OPEN-NOTEBOOK LOAD TEST — {num_users} concurrent users")
    print(f"total requests={len(results)}  passed={len(passed)}  failed={len(failed)}"
          f"  wall_time={total_elapsed:.1f}s")
    print("=" * 72)

    by_endpoint: dict[str, list[StepResult]] = {}
    for r in results:
        by_endpoint.setdefault(r.endpoint, []).append(r)

    header = (f"  {'endpoint':<28} {'total':>6} {'passed':>7} {'failed':>7}"
              f" {'avg(s)':>8} {'min(s)':>8} {'max(s)':>8}")
    print(header)
    print("  " + "-" * 74)

    ordered = [
        "search",
        "global-chat/sessions",
        "global-chat/execute",
        "research/generate",
        "research/jobs/poll",
    ]
    for ep in ordered:
        ep_results = by_endpoint.get(ep, [])
        if not ep_results:
            continue
        ok = sum(1 for r in ep_results if r.success)
        times = [r.elapsed for r in ep_results]
        avg = sum(times) / len(times)
        print(f"  {'/' + ep:<28} {len(ep_results):>6} {ok:>7} {len(ep_results)-ok:>7}"
              f" {avg:>8.2f} {min(times):>8.2f} {max(times):>8.2f}")

    if failed:
        print("\nFailed requests:")
        for r in failed:
            print(f"  - {r.label}  ({r.error})")

    rate_limited = [r for r in results if r.status_code == 429]
    if rate_limited:
        print(f"\n[!] Rate-limited requests: {len(rate_limited)}")
        for r in rate_limited:
            print(f"  - {r.label}")

    print()


def export_results_to_json(results: list[StepResult], total_elapsed: float, num_users: int, filename="resultados.json"):
    """
    Exporta as estatísticas finais para um ficheiro JSON 
    pronto a ser consumido pelo script de geração de gráficos.
    """
    passed = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    data = {
        "test_metadata": {
            "concurrent_users": num_users,
            "total_requests": len(results),
            "passed": len(passed),
            "failed": len(failed),
            "wall_time_seconds": round(total_elapsed, 2)
        },
        "endpoints": []
    }

    by_endpoint: dict[str, list[StepResult]] = {}
    for r in results:
        by_endpoint.setdefault(r.endpoint, []).append(r)

    ordered = [
        "search",
        "global-chat/sessions",
        "global-chat/execute",
        "research/generate",
        "research/jobs/poll",
    ]

    for ep in ordered:
        ep_results = by_endpoint.get(ep, [])
        if not ep_results:
            continue
        ok = sum(1 for r in ep_results if r.success)
        times = [r.elapsed for r in ep_results]
        avg = sum(times) / len(times) if times else 0

        data["endpoints"].append({
            "name": f"/{ep}",
            "total": len(ep_results),
            "passed": ok,
            "failed": len(ep_results) - ok,
            "avg_time_s": round(avg, 2),
            "min_time_s": round(min(times), 2) if times else 0,
            "max_time_s": round(max(times), 2) if times else 0
        })

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    print(f"[+] Resultados exportados para JSON com sucesso: {filename}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Demo load test: simulates concurrent open-notebook users")
    parser.add_argument("--users", type=int, default=NUM_USERS,
                        help=f"Number of simulated users (default: {NUM_USERS})")
    parser.add_argument("--url", type=str, default=BASE_URL,
                        help=f"Base API URL (default: {BASE_URL})")
    parser.add_argument("--password", type=str, default="",
                        help="API password (OPEN_NOTEBOOK_PASSWORD). "
                             "Leave empty if the server has no password set.")
    parser.add_argument("--think", type=float, default=DEFAULT_THINK_TIME,
                        help=f"Mean think time in seconds between requests "
                             f"(default: {DEFAULT_THINK_TIME})")
    args = parser.parse_args()

    random.seed(42)
    n = args.users

    all_users = list(range(1, n + 1))
    random.shuffle(all_users)
    n_async = max(1, round(n * GLOBAL_CHAT_USERS_RATIO))
    chat_users = set(all_users[:n_async])
    research_users = set(all_users[n_async: n_async * 2])

    # ── Sanity-check the server is up ────────────────────────────────────────
    try:
        hc = requests.get(f"{args.url}/api/health", timeout=10,
                          headers=_auth_headers(args.password, 0))
        hc.raise_for_status()
    except Exception as exc:
        print(f"[ERROR] Cannot reach {args.url}/health: {exc}")
        sys.exit(2)

    print("Open-Notebook Demo Load Test")
    print(f"  base_url    : {args.url}")
    print(f"  users       : {n}  (all do 3 text searches)")
    print(f"  global chat : {len(chat_users)} users also open a chat session + 2 turns")
    print(f"  research    : {len(research_users)} users also submit a research job")
    print(f"  think time  : ~{args.think}s mean between requests")
    total_req_min = n * 3 + len(chat_users) * 3 + len(research_users) * 2
    print(f"  minimum total requests: {total_req_min}")
    print("-" * 72)

    all_results: list[StepResult] = []
    print_lock = threading.Lock()
    t_start = time.monotonic()

    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = {
            pool.submit(
                simulate_user,
                uid, args.url, args.password, args.think,
                uid in chat_users,
                uid in research_users,
                print_lock,
            ): uid
            for uid in range(1, n + 1)
        }
        for future in as_completed(futures):
            steps = future.result()
            all_results.extend(steps)

    total_elapsed = time.monotonic() - t_start
    print_summary(all_results, total_elapsed, n)
    
    # Exporta o JSON no final do teste
    export_results_to_json(all_results, total_elapsed, n)

    failed_count = sum(1 for r in all_results if not r.success)
    sys.exit(0 if failed_count == 0 else 1)


if __name__ == "__main__":
    main()