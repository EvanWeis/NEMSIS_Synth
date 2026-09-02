"""Sweep a Schematron rule set against NEMSIS's official 196-case test corpus.

Each case ships with an expected verdict, so this measures a rule set's coverage
rather than assuming it. Run it after pointing `--rules` at a state or agency rule
set to see how much of the national corpus that set actually reproduces.

Usage:
    python scripts/eval_schematron.py [--rules path/to/rules.sch]
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

from nemsis_gen.schematron import DEFAULT_RULES, validate

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "reference" / "samples" / "_stale_package" / "Schematron" / "EMS"


def parse_expectations(tests_txt: Path) -> list[tuple[str, str, str]]:
    """Return (filename, expected verdict, description) for every corpus case."""
    text = tests_txt.read_text(encoding="utf-8", errors="replace")
    cases = []
    for block in text.split("File:")[1:]:
        filename = block.split()[0]
        verdict = re.search(r"Expected Result:\s*\[(\w+)\]", block)
        description = block.split("Description:")[1].split("Expected")[0]
        cases.append(
            (
                filename,
                verdict.group(1) if verdict else "UNKNOWN",
                " ".join(description.split()),
            )
        )
    return cases


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--show-missed", action="store_true")
    args = parser.parse_args()

    cases = parse_expectations(CORPUS / "Tests.txt")
    print(f"corpus: {len(cases)} cases   expected verdicts: {Counter(v for _f, v, _d in cases)}")
    print(f"rules:  {args.rules.name}\n")

    tallies: Counter[str] = Counter()
    missed = []
    for filename, expected, description in cases:
        path = CORPUS / "xml" / filename
        if not path.exists():
            tallies["case file missing"] += 1
            continue
        result = validate(path, args.rules)
        if not result.ran:
            tallies["engine could not run (unparseable case)"] += 1
            continue
        flagged = bool(result.errors)

        if expected == "ERROR":
            tallies["ERROR flagged" if flagged else "ERROR missed"] += 1
            if not flagged:
                missed.append((filename, description))
        elif flagged:
            tallies[f"{expected} but flagged (FALSE POSITIVE)"] += 1
        else:
            tallies[f"{expected} not flagged"] += 1

    width = max(len(k) for k in tallies)
    for label, count in sorted(tallies.items()):
        print(f"  {label:<{width}}  {count}")

    if args.show_missed and missed:
        print("\nERROR cases this rule set does not cover:")
        for filename, description in missed:
            print(f"  {filename:<34} {description[:96]}")


if __name__ == "__main__":
    main()
