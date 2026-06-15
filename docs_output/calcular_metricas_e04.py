#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cálculo de métricas E04 com evidência real da API.

Execução recomendada:
  conda activate navy
  cd /user/home/mf.domingos/navy/open-notebook/docs_output
  python3 calcular_metricas_e04.py

Saídas:
  metricas_e04/metricas_resumo.json
  metricas_e04/search_benchmark.csv
  metricas_e04/audit_actions.csv
  metricas_e04/benchmark_search_latency.png (opcional)
  metricas_e04/audit_actions_top10.png (opcional)
  metricas_e04/audit_status_ratio.png (opcional)
"""

from __future__ import annotations

import csv
import json
import os
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

BASE_URL = os.getenv("OPEN_NOTEBOOK_BASE_URL", "http://127.0.0.1:5055")
EMAIL = os.getenv("OPEN_NOTEBOOK_EMAIL", "admin@example.com")
PASSWORD = os.getenv("OPEN_NOTEBOOK_PASSWORD", "admin123")
VERIFY_TLS = os.getenv("OPEN_NOTEBOOK_VERIFY_TLS", "false").lower() == "true"
TIMEOUT_S = float(os.getenv("OPEN_NOTEBOOK_TIMEOUT_SECONDS", "120"))
ITERATIONS = int(os.getenv("E04_BENCH_ITERS", "3"))
INCLUDE_ASK_SIMPLE = os.getenv("E04_INCLUDE_ASK_SIMPLE", "true").lower() == "true"
OUT_DIR = Path("/user/home/mf.domingos/navy/open-notebook/docs_output/metricas_e04")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_get(d: Dict[str, Any], key: str, default: Any):
    v = d.get(key)
    return default if v is None else v


def percentile(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    values = sorted(values)
    k = (len(values) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    d0 = values[f] * (c - k)
    d1 = values[c] * (k - f)
    return d0 + d1


def parse_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("items", "results", "data", "sources", "notebooks", "notes", "models", "credentials"):
            v = payload.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def count_from_payload(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        if isinstance(payload.get("count"), int):
            return int(payload["count"])
        if isinstance(payload.get("total"), int):
            return int(payload["total"])
        items = parse_items(payload)
        if items:
            return len(items)
    return 0


def login(session: requests.Session) -> str:
    url = f"{BASE_URL}/api/auth/login/local"
    resp = session.post(
        url,
        json={"email": EMAIL, "password": PASSWORD},
        timeout=TIMEOUT_S,
        verify=VERIFY_TLS,
    )
    resp.raise_for_status()
    data = resp.json() if resp.content else {}

    token = data.get("access_token") or data.get("token")
    if not token and isinstance(data.get("data"), dict):
        token = data["data"].get("access_token") or data["data"].get("token")
    if not token:
        raise RuntimeError("Não foi possível obter token JWT no login.")
    return token


def timed_request(
    session: requests.Session,
    method: str,
    path: str,
    token: Optional[str] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> Tuple[float, int, Any]:
    url = f"{BASE_URL}{path}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    t0 = time.perf_counter()
    resp = session.request(
        method,
        url,
        headers=headers,
        json=json_body,
        timeout=TIMEOUT_S,
        verify=VERIFY_TLS,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    try:
        payload = resp.json() if resp.content else None
    except Exception:
        payload = {"raw": resp.text[:500]} if resp.text else None

    return elapsed_ms, resp.status_code, payload


def benchmark_search(session: requests.Session, token: str) -> Dict[str, Any]:
    _, defaults_status, defaults_payload = timed_request(
        session,
        "GET",
        "/api/models/defaults",
        token=token,
    )
    if defaults_status >= 400 or not isinstance(defaults_payload, dict):
        defaults_payload = {}

    strategy_model = defaults_payload.get("default_tools_model") or defaults_payload.get("default_chat_model")
    answer_model = defaults_payload.get("default_chat_model")
    final_answer_model = defaults_payload.get("default_chat_model")

    if not (strategy_model and answer_model and final_answer_model):
        _, models_status, models_payload = timed_request(session, "GET", "/api/models", token=token)
        if models_status < 400:
            models = parse_items(models_payload)
            language_models = [m for m in models if str(m.get("type") or "") == "language"]
            if language_models:
                fallback = language_models[0].get("id")
                strategy_model = strategy_model or fallback
                answer_model = answer_model or fallback
                final_answer_model = final_answer_model or fallback

    scenarios = {
        "text": {
            "path": "/api/search",
            "body": {"query": "Marinha", "type": "text", "limit": 5},
        },
        "vector": {
            "path": "/api/search",
            "body": {"query": "Marinha", "type": "vector", "limit": 5},
        },
        "hybrid": {
            "path": "/api/search",
            "body": {"query": "Marinha", "type": "hybrid", "limit": 5},
        },
    }

    if INCLUDE_ASK_SIMPLE and (strategy_model and answer_model and final_answer_model):
        scenarios["ask_simple"] = {
            "path": "/api/search/ask/simple",
            "body": {
                "question": "Resumo operacional do sistema",
                "strategy_model": strategy_model,
                "answer_model": answer_model,
                "final_answer_model": final_answer_model,
            },
        }

    results: Dict[str, Any] = {}

    for name, cfg in scenarios.items():
        times: List[float] = []
        statuses: List[int] = []

        # ask/simple e uma chamada cara (geracao RAG); corre 1 vez por defeito.
        iters = 1 if name == "ask_simple" else ITERATIONS

        for _ in range(iters):
            elapsed, status, _ = timed_request(
                session,
                "POST",
                cfg["path"],
                token=token,
                json_body=cfg["body"],
            )
            times.append(elapsed)
            statuses.append(status)

        results[name] = {
            "iterations": iters,
            "status_codes": dict(Counter(statuses)),
            "min_ms": min(times) if times else None,
            "avg_ms": statistics.mean(times) if times else None,
            "median_ms": statistics.median(times) if times else None,
            "p95_ms": percentile(times, 95.0),
            "max_ms": max(times) if times else None,
            "samples_ms": times,
        }

    return results


def fetch_audit_metrics(session: requests.Session, token: str) -> Dict[str, Any]:
    elapsed, status, payload = timed_request(
        session,
        "GET",
        "/api/audit/logs?limit=1000",
        token=token,
    )

    logs = parse_items(payload)
    actions = Counter()
    statuses = Counter()
    durations = []
    durations_by_action: Dict[str, List[float]] = {}

    for row in logs:
        action = str(row.get("action") or "unknown")
        actions[action] += 1

        stat = str(row.get("status") or "unknown")
        statuses[stat] += 1

        dur = row.get("duration_ms")
        if isinstance(dur, (int, float)):
            durations.append(float(dur))
            durations_by_action.setdefault(action, []).append(float(dur))

    total = len(logs)
    ok = statuses.get("success", 0)
    success_rate = f"{(ok / total * 100.0):.2f}%" if total else "N/D"

    def _stats(values: List[float]) -> Dict[str, Any]:
        return {
            "min": min(values) if values else None,
            "avg": statistics.mean(values) if values else None,
            "median": statistics.median(values) if values else None,
            "p95": percentile(values, 95.0),
            "max": max(values) if values else None,
            "samples": len(values),
        }

    # token_refresh domina os registos e distorce os percentis globais.
    # Reportamos tambem as duracoes excluindo token_refresh para leitura util.
    durations_excl_refresh = [
        d
        for action, vals in durations_by_action.items()
        if action != "token_refresh"
        for d in vals
    ]

    per_action_stats = {
        action: _stats(vals)
        for action, vals in sorted(durations_by_action.items())
    }

    return {
        "request_status": status,
        "request_latency_ms": elapsed,
        "total_logs": total,
        "actions": dict(actions),
        "status_distribution": dict(statuses),
        "success_rate": success_rate,
        "duration_ms": _stats(durations),
        "duration_ms_excl_token_refresh": _stats(durations_excl_refresh),
        "duration_ms_by_action": per_action_stats,
    }


def fetch_entity_counts(session: requests.Session, token: str) -> Dict[str, int]:
    paths = {
        "models": "/api/models",
        "credentials": "/api/credentials",
        "notebooks": "/api/notebooks",
        "notes": "/api/notes",
        "sources": "/api/sources",
    }
    out: Dict[str, int] = {}

    for k, path in paths.items():
        _, status, payload = timed_request(session, "GET", path, token=token)
        if status >= 400:
            out[k] = -1
        else:
            out[k] = count_from_payload(payload)

    return out


def fetch_health(session: requests.Session, token: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {}

    for path, key in [
        ("/health", "health"),
        ("/api/health", "api_health"),
        ("/api/config", "api_config"),
        ("/api/auth/status", "auth_status"),
    ]:
        elapsed, status, payload = timed_request(session, "GET", path, token=token)
        data[key] = {
            "status_code": status,
            "latency_ms": elapsed,
            "payload": payload,
        }

    return data


def write_csv(path: Path, headers: List[str], rows: List[List[Any]]):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for row in rows:
            w.writerow(row)


def write_artifacts(summary: Dict[str, Any]):
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    (OUT_DIR / "metricas_resumo.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    sb = summary.get("search_benchmark", {})
    rows = []
    for scenario in ("text", "vector", "hybrid", "ask_simple"):
        v = sb.get(scenario, {})
        rows.append([
            scenario,
            safe_get(v, "iterations", "N/D"),
            safe_get(v, "min_ms", "N/D"),
            safe_get(v, "avg_ms", "N/D"),
            safe_get(v, "median_ms", "N/D"),
            safe_get(v, "p95_ms", "N/D"),
            safe_get(v, "max_ms", "N/D"),
            json.dumps(safe_get(v, "status_codes", {}), ensure_ascii=False),
        ])

    write_csv(
        OUT_DIR / "search_benchmark.csv",
        ["scenario", "iterations", "min_ms", "avg_ms", "median_ms", "p95_ms", "max_ms", "status_codes"],
        rows,
    )

    audit = summary.get("audit", {})
    actions = audit.get("actions", {})
    action_rows = [[k, v] for k, v in sorted(actions.items(), key=lambda x: x[1], reverse=True)]
    write_csv(OUT_DIR / "audit_actions.csv", ["action", "count"], action_rows)


def try_generate_charts(summary: Dict[str, Any]) -> Dict[str, str]:
    status: Dict[str, str] = {}
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover
        return {"charts": f"não gerados ({exc})"}

    sb = summary.get("search_benchmark", {})
    labels = ["text", "vector", "hybrid", "ask_simple"]
    avgs = [safe_get(sb.get(k, {}), "avg_ms", 0) or 0 for k in labels]

    plt.figure(figsize=(8, 4.5))
    bars = plt.bar(labels, avgs)
    plt.title("Latência média por cenário de pesquisa")
    plt.ylabel("ms")
    for b, val in zip(bars, avgs):
        plt.text(b.get_x() + b.get_width() / 2, b.get_height(), f"{val:.1f}", ha="center", va="bottom", fontsize=9)
    plt.tight_layout()
    p1 = OUT_DIR / "benchmark_search_latency.png"
    plt.savefig(p1, dpi=140)
    plt.close()
    status["benchmark_search_latency.png"] = "ok"

    audit = summary.get("audit", {})
    actions = audit.get("actions", {})
    top = sorted(actions.items(), key=lambda x: x[1], reverse=True)[:10]
    if top:
        x = [k for k, _ in top]
        y = [v for _, v in top]
        plt.figure(figsize=(10, 5))
        plt.barh(x[::-1], y[::-1])
        plt.title("Top 10 ações de auditoria")
        plt.xlabel("contagem")
        plt.tight_layout()
        p2 = OUT_DIR / "audit_actions_top10.png"
        plt.savefig(p2, dpi=140)
        plt.close()
        status["audit_actions_top10.png"] = "ok"

    st = audit.get("status_distribution", {})
    if st:
        labels2 = list(st.keys())
        values2 = [st[k] for k in labels2]
        plt.figure(figsize=(6, 6))
        plt.pie(values2, labels=labels2, autopct="%1.1f%%", startangle=90)
        plt.title("Distribuição de estados em auditoria")
        plt.tight_layout()
        p3 = OUT_DIR / "audit_status_ratio.png"
        plt.savefig(p3, dpi=140)
        plt.close()
        status["audit_status_ratio.png"] = "ok"

    return status


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    summary: Dict[str, Any] = {
        "generated_at": now_iso(),
        "base_url": BASE_URL,
        "iterations": ITERATIONS,
        "notes": [
            "Métricas calculadas exclusivamente a partir de endpoints e logs observáveis.",
            "Sem inventar resultados; valores indisponíveis são marcados como N/D.",
        ],
    }

    with requests.Session() as session:
        token = login(session)
        summary["health"] = fetch_health(session, token)
        summary["entities"] = fetch_entity_counts(session, token)
        summary["audit"] = fetch_audit_metrics(session, token)
        summary["search_benchmark"] = benchmark_search(session, token)

    write_artifacts(summary)
    chart_status = try_generate_charts(summary)
    summary["chart_status"] = chart_status

    (OUT_DIR / "metricas_resumo.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("Métricas E04 calculadas com sucesso.")
    print(f"Saída: {OUT_DIR}")
    print(json.dumps({"chart_status": chart_status}, ensure_ascii=False))


if __name__ == "__main__":
    main()
