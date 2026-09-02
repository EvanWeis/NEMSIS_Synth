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
    family: str
    description: str
    narrative_quality: int
    effort: str
    mutation: Mutation | None
    defect: str
    expected_findings: tuple[str, ...]
    ingestible: bool

    @property
    def expects_valid(self) -> bool:
        """Whether a correct run should produce an ingestible file.

        Almost every tier is ingestible on purpose: NEMSIS is the wire format, not
        the thing under test, and a record that will not load never reaches the QA
        tool. Only the ingestion_guard family is meant to fail.
        """
        return self.ingestible


@dataclass(frozen=True)
class ProfileConfig:
    profiles: dict[str, Profile]
    narrative_rubric: dict[int, str]

    def by_family(self) -> dict[str, list[Profile]]:
        families: dict[str, list[Profile]] = {}
        for profile in self.profiles.values():
            families.setdefault(profile.family, []).append(profile)
        return families

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
            family=str(raw.get("family", "uncategorised")),
            description=" ".join(raw["description"].split()),
            narrative_quality=int(raw["narrative_quality"]),
            effort=str(raw.get("effort", "high")),
            mutation=Mutation(mutation["name"], mutation.get("params") or {}) if mutation else None,
            defect=(raw.get("defect") or "").strip(),
            expected_findings=tuple(raw.get("expected_findings") or ()),
            ingestible=bool(raw.get("ingestible", mutation is None)),
        )
    rubric = {int(k): v for k, v in data["narrative_rubric"].items()}
    return ProfileConfig(profiles=profiles, narrative_rubric=rubric)


def load_system_base(path: Path = SYSTEM_BASE_PATH) -> str:
    return path.read_text(encoding="utf-8")


def narrative_instruction_text(profile: Profile, config: ProfileConfig) -> str:
    """The per-profile system block: rubric level, plus any deliberate defect."""
    blocks = [
        f"## Quality profile: {profile.name}",
        profile.description,
        f"### Narrative quality target: {profile.narrative_quality} of 5",
        config.rubric_for(profile.narrative_quality),
    ]
    if profile.defect:
        blocks += [
            "### Deliberate defect for this tier",
            profile.defect,
            (
                "The record must remain fully ingestible: schema-valid, correctly "
                "coded, structurally clean. The defect lives in the clinical "
                "content only. Introduce no defect other than the one described - "
                "this record is a labelled fixture, and an extra flaw makes it "
                "useless as ground truth."
            ),
        ]
    return "\n\n".join(
        blocks
        + [
            (
                "The narrative must land at exactly this level. Apart from any "
                "deliberate defect above, every other part of the record stays "
                "clinically coherent and schema-valid."
            ),
        ]
    )
