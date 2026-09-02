"""The five generation inputs, as a typed, reproducible object.

A scenario is a file, not a shell string, so a bulk run can be re-run and a
manifest row can point at exactly what produced a record.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from dataclasses import field as dc_field
from pathlib import Path

import yaml


@dataclass
class Scenario:
    """Condition/patient, scene, assessment, interventions, narrative outline."""

    name: str = "unnamed"
    patient: dict = dc_field(default_factory=dict)
    scene: dict = dc_field(default_factory=dict)
    assessment: dict = dc_field(default_factory=dict)
    interventions: list = dc_field(default_factory=list)
    narrative_outline: str = ""
    free_text: str = ""

    @classmethod
    def from_file(cls, path: Path) -> Scenario:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown scenario keys: {sorted(unknown)}")
        return cls(**data)

    @classmethod
    def from_text(cls, text: str, name: str = "adhoc") -> Scenario:
        """The --scenario convenience path: prose in, same object out."""
        return cls(name=name, free_text=text.strip())

    def to_prompt_block(self) -> str:
        parts = [f"Scenario name: {self.name}"]
        for label, value in (
            ("Patient", self.patient),
            ("Scene", self.scene),
            ("Assessment", self.assessment),
            ("Interventions", self.interventions),
        ):
            if value:
                parts.append(f"{label}:\n{yaml.safe_dump(value, sort_keys=False).strip()}")
        if self.narrative_outline:
            parts.append(f"Narrative outline:\n{self.narrative_outline.strip()}")
        if self.free_text:
            parts.append(f"Clinical scenario:\n{self.free_text}")
        return "\n\n".join(parts)

    def to_json(self) -> dict:
        return asdict(self)
