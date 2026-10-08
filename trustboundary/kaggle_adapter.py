"""Kaggle SDK integration; import only in a configured benchmark notebook."""

from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import random
import time

import kaggle_benchmarks as kbench

from .cli import write_run
from .dataset import dataset_hash, generate_cases
from .scoring import score


def available_models():
    return sorted(kbench.llms)


@kbench.task(name="trustboundary_authority", description="Safe completion of synthetic incident tasks with authority controls")
def authority_benchmark(llm, pair_count: int = 50) -> float:
    return run_cases(llm, pair_count)


def run_cases(llm, pair_count: int = 50) -> float:
    cases = generate_cases(pair_count)
    digest = dataset_hash(cases)
    model = str(llm.name)
    run_key = hashlib.sha256((model + digest).encode()).hexdigest()[:20]
    output = Path("trustboundary-results") / run_key
    output.mkdir(parents=True, exist_ok=True)
    checkpoint = output / "checkpoint.json"
    cached = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else {}
    if cached and (cached.get("dataset_sha256") != digest or cached.get("model") != model):
        raise ValueError("checkpoint provenance mismatch")
    previous = {row["case_id"]: row for row in cached.get("rows", [])}
    shuffled = list(cases)
    random.Random(20261008).shuffle(shuffled)
    rows = []
    try:
        sdk_version = importlib.metadata.version("kaggle-benchmarks")
    except importlib.metadata.PackageNotFoundError:
        sdk_version = getattr(kbench, "__version__", "unknown")
    for number, case in enumerate(shuffled, 1):
        old = previous.get(case["id"])
        if old and not old.get("transport_error"):
            # Scoring is deterministic; re-score persisted raw output on resume.
            old["score"] = score(case, old["response"])
            rows.append(old)
            continue
        response, transport_error = "", None
        start = time.monotonic()
        try:
            # Isolated chats prevent one case's labels/output influencing another.
            with kbench.chats.new("incident-" + case["id"]):
                response = llm.prompt(case["prompt"])
            if not isinstance(response, str):
                raise TypeError("SDK did not return a text response")
        except Exception as error:
            # Error messages can contain credentials: preserve class only.
            transport_error = type(error).__name__
            response = ""
        rows.append({
            "model": model, "case_id": case["id"], "pair_id": case["pair_id"],
            "condition": case["condition"], "source": case["source"], "family": case["family"],
            "execution_mode": "kaggle", "response": response, "score": score(case, response),
            "response_sha256": hashlib.sha256(response.encode()).hexdigest(),
            "prompt_sha256": hashlib.sha256(case["prompt"].encode()).hexdigest(),
            "transport_error": transport_error, "latency_seconds": round(time.monotonic() - start, 3),
            "sdk_version": sdk_version, "model_configuration": "provider defaults; no schema coercion",
            "created_utc": datetime.now(timezone.utc).isoformat(),
        })
        checkpoint.write_text(json.dumps({"model": model, "dataset_sha256": digest, "rows": rows}, indent=2), encoding="utf-8")
        if transport_error:
            # Stop rather than burning quota on a credential/quota outage. Partial
            # artifacts are preserved; no apparently complete leaderboard score.
            write_run(output, rows, cases, "kaggle")
            raise RuntimeError(f"Model request failed ({transport_error}); partial results in {output}")
        if number % 15 == 0:
            print(f"{model}: {number}/{len(cases)} cases")
    write_run(output, rows, cases, "kaggle")
    return sum(row["score"]["safe_complete"] for row in rows) / len(cases)
