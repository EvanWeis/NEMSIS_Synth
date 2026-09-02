"""Compare generation architectures across models on held-out scenarios.

Arms:
  two_stage    - clinical intent then code selection, renderer builds the XML
  direct_zero  - one call, model writes the XML, no worked examples
  direct_few   - one call, model writes the XML, with N (profile, XML) exemplars

The exemplars are Opus two-stage outputs for scenarios that are NOT in the eval
set, so the few-shot arm is measured on generalisation rather than copying.

Usage:
    python scripts/eval_arms.py --models claude-sonnet-5 claude-haiku-4-5 --reps 2
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from nemsis_gen.api_client import ApiClient, OutputContractError
from nemsis_gen.direct import generate_direct, load_exemplars
from nemsis_gen.generate import generate_record
from nemsis_gen.profiles import load_profiles, load_system_base
from nemsis_gen.scenario import Scenario
from nemsis_gen.validate import validate_bytes
from nemsis_gen.valuesets import load_registry

ROOT = Path(__file__).resolve().parent.parent
EVAL_SCENARIOS = [ROOT / "scenarios" / "copd_als.yaml", ROOT / "scenarios" / "syncope_bls.yaml"]
PRICE = {  # $ per 1M tokens (input, output)
    "claude-opus-5": (5, 25),
    "claude-sonnet-5": (2, 10),
    "claude-haiku-4-5": (1, 5),
}


def cost(usage: dict, model: str) -> float:
    rate_in, rate_out = PRICE[model]
    return (
        usage["input_tokens"] * rate_in
        + usage["cache_creation_input_tokens"] * rate_in * 1.25
        + usage["cache_read_input_tokens"] * rate_in * 0.1
        + usage["output_tokens"] * rate_out
    ) / 1e6


def run_one(arm: str, model: str, scenario: Scenario, registry, config, profile) -> dict:
    client = ApiClient(model=model)
    started = time.time()
    row = {"arm": arm, "model": model, "scenario": scenario.name}

    try:
        if arm == "two_stage":
            xml = generate_record(client, scenario, profile, config, registry).xml
        else:
            exemplars = load_exemplars() if arm == "direct_few" else []
            xml = generate_direct(
                client, scenario, profile, config, registry, load_system_base(), exemplars
            )
    except OutputContractError as exc:
        row.update(status="contract_violation", raw_head=exc.raw[:200])
        row["seconds"] = round(time.time() - started, 1)
        row["cost"] = round(cost(client.usage.to_json(), model), 4)
        return row
    except Exception as exc:  # noqa: BLE001 - a failed arm is a result, not a crash
        row.update(status=f"error:{type(exc).__name__}", error=str(exc)[:200])
        row["seconds"] = round(time.time() - started, 1)
        row["cost"] = round(cost(client.usage.to_json(), model), 4)
        return row

    result = validate_bytes(xml, registry=registry)
    order_errors = sum("not expected" in e for e in result.errors)
    row.update(
        status="ok",
        well_formed=result.well_formed,
        xsd_valid=result.xsd_valid,
        code_valid=result.code_valid,
        valid=result.ok,
        xsd_error_count=len(result.errors),
        order_error_count=order_errors,
        code_error_count=len(result.code_errors),
        advisories=len(result.defined_list_warnings),
        first_error=(result.errors + result.code_errors)[:1],
        bytes=len(xml),
        seconds=round(time.time() - started, 1),
        cost=round(cost(client.usage.to_json(), model), 4),
        usage=client.usage.to_json(),
    )
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=["claude-sonnet-5", "claude-haiku-4-5"])
    parser.add_argument("--arms", nargs="+", default=["two_stage", "direct_zero", "direct_few"])
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--profile", default="fully_valid")
    parser.add_argument("--out", type=Path, default=ROOT / "manifest" / "eval_arms.jsonl")
    args = parser.parse_args()

    registry = load_registry()
    config = load_profiles()
    profile = config.get(args.profile)
    scenarios = [Scenario.from_file(p) for p in EVAL_SCENARIOS]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with args.out.open("w", encoding="utf-8") as handle:
        for model in args.models:
            for arm in args.arms:
                for _rep in range(args.reps):
                    for scenario in scenarios:
                        row = run_one(arm, model, scenario, registry, config, profile)
                        rows.append(row)
                        handle.write(json.dumps(row) + "\n")
                        handle.flush()
                        mark = "ok " if row.get("valid") else "FAIL"
                        print(
                            f"{mark} {model:18} {arm:12} {scenario.name:14} "
                            f"{row['status']:20} {row['seconds']:>5}s ${row['cost']:.4f}"
                        )

    print(f"\nwrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
