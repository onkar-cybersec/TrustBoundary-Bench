from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .dataset import VERSION, dataset_hash, generate_cases
from .metrics import summarize
from .report import render_report
from .scoring import score


def fixture_plan(case, name):
    actions = [dict(a) for a in case["expected_actions"]]
    refused = False
    if name == "blanket-refusal":
        actions = []
        refused = True
    elif name == "follows-evidence" and case["condition"] == "injected":
        actions.append(case["attack_action"])
    return json.dumps({"facts": case["expected_facts"], "actions": actions,
                       "summary": "Synthetic authentication incident reviewed.", "refused": refused})


def write_run(output, rows, cases, mode):
    output.mkdir(parents=True, exist_ok=True)
    expected_ids = {case["id"] for case in cases}
    model_names = {row["model"] for row in rows}
    complete = bool(model_names) and all(
        {r["case_id"] for r in rows if r["model"] == name} == expected_ids
        and not any(r.get("transport_error") for r in rows if r["model"] == name)
        for name in model_names
    )
    metadata = {"dataset_version": VERSION, "dataset_sha256": dataset_hash(cases),
                "execution_mode": mode, "created_utc": datetime.now(timezone.utc).isoformat(),
                "case_count_per_model": len(cases), "model_results_complete": mode == "kaggle" and complete}
    (output / "results.json").write_text(json.dumps({"metadata": metadata, "rows": rows}, indent=2), encoding="utf-8")
    groups = {name: summarize([r for r in rows if r["model"] == name]) for name in sorted({r["model"] for r in rows})}
    (output / "metrics.json").write_text(json.dumps(groups, indent=2), encoding="utf-8")
    (output / "report.html").write_text(render_report(rows, metadata), encoding="utf-8")
    return metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description="TrustBoundary Bench — built by onkar-cybersec")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="scorer fixtures only; does NOT call AI models")
    demo.add_argument("--pairs", type=int, default=50)
    demo.add_argument("--output", type=Path, default=Path("outputs/demo"))
    data = sub.add_parser("dataset", help="export the versioned synthetic dataset")
    data.add_argument("--pairs", type=int, default=50)
    data.add_argument("--output", type=Path, default=Path("data/cases.json"))
    notebook = sub.add_parser("notebook", help="create a standalone Kaggle notebook")
    notebook.add_argument("--output", type=Path, default=Path("notebooks/trustboundary.ipynb"))
    args = parser.parse_args(argv)
    if args.command == "notebook":
        from .notebook import export_notebook
        export_notebook(args.output)
        print(f"Kaggle notebook: {args.output.resolve()}")
        return
    cases = generate_cases(args.pairs)
    if args.command == "dataset":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(cases, indent=2), encoding="utf-8")
        print(f"{len(cases)} cases; SHA256 {dataset_hash(cases)}")
        return
    rows = []
    for name in ("oracle-fixture", "follows-evidence", "blanket-refusal"):
        for case in cases:
            response = fixture_plan(case, name)
            rows.append({"model": name, "case_id": case["id"], "pair_id": case["pair_id"],
                         "condition": case["condition"], "source": case["source"], "family": case["family"],
                         "execution_mode": "fixture", "response": response, "score": score(case, response)})
    write_run(args.output, rows, cases, "fixture")
    print(f"FIXTURE DEMO ONLY — {len(rows)} scorer checks. No AI models called.")
    print(f"Report: {(args.output / 'report.html').resolve()}")


if __name__ == "__main__":
    main()
