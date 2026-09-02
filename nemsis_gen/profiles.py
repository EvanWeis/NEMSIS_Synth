"""Quality-profile configuration.

Profiles are data, not code: a new tier is a block in ``prompts/profiles.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
PROFILES_PATH = PROMPTS_DIR / "profiles.yaml"
SYSTEM_BASE_PATH = PROMPTS_DIR / "system_base.md"


@dataclass(frozen=True)
class Mutation:
    name: str
    params: dict


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    narrative_quality: int
    effort: str
    mutation: Mutation | None

    @property
    def expects_valid(self) -> bool:
        """Whether a correct run of this profile should produce a valid file."""
        return self.mutation is None


@dataclass(frozen=True)
class ProfileConfig:
    profiles: dict[str, Profile]
    narrative_rubric: dict[int, str]

    def get(self, name: str) -> Profile:
        if name not in self.profiles:
            known = ", ".join(sorted(self.profiles))
            raise KeyError(f"unknown profile {name!r}; known profiles: {known}")
        return self.profiles[name]

    def rubric_for(self, quality: int) -> str:
        return self.narrative_rubric[quality].strip()


@lru_cache(maxsize=2)
def load_profiles(path: Path = PROFILES_PATH) -> ProfileConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    profiles = {}
    for name, raw in data["profiles"].items():
        mutation = raw.get("mutation")
        profiles[name] = Profile(
            name=name,
            description=" ".join(raw["description"].split()),
            narrative_quality=int(raw["narrative_quality"]),
            effort=str(raw.get("effort", "high")),
            mutation=Mutation(mutation["name"], mutation.get("params") or {}) if mutation else None,
        )
    rubric = {int(k): v for k, v in data["narrative_rubric"].items()}
    return ProfileConfig(profiles=profiles, narrative_rubric=rubric)


def load_system_base(path: Path = SYSTEM_BASE_PATH) -> str:
    return path.read_text(encoding="utf-8")
