"""Append-only JSONL run log."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


class Manifest:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, row: dict) -> None:
        row = {"timestamp": datetime.now(UTC).isoformat(), **row}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [
            json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line
        ]
