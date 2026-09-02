"""Single-call generation: the model writes the XML document itself.

This exists to be measured against the two-stage pipeline in
:mod:`nemsis_gen.generate`, not because it is recommended. The two-stage design
makes a claim - that having the model emit XML directly costs you element
ordering, namespace correctness and code discipline - and a claim like that
should be tested rather than asserted.

Two variants:

* **zero-shot** - structural rules and the code catalogue, no worked examples.
* **few-shot** - the same, plus N (scenario profile, finished XML) exemplar
  pairs. Exemplars must come from scenarios that are *not* in the eval set, or
  the arm is measuring copying rather than generalisation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .api_client import ApiClient
from .generate import build_code_catalogue, load_fieldplan
from .profiles import Profile, ProfileConfig, narrative_instruction_text
from .scenario import Scenario
from .valuesets import Registry

EXEMPLAR_DIR = Path(__file__).resolve().parent.parent / "reference" / "exemplars"

MARKER_OPEN = "<xml>"
MARKER_CLOSE = "</xml>"

STRUCTURAL_RULES = """
## Output: a complete NEMSIS v3.5.0 EMSDataSet XML document

Root element `EMSDataSet`, default namespace `http://www.nemsis.org`, with
`xsi:schemaLocation="http://www.nemsis.org http://nemsis.org/media/nemsis_v3/release-3.5.0/XSDs/NEMSIS_XSDs/EMSDataSet_v3.xsd"`.

Shape: `EMSDataSet > Header > (DemographicGroup, PatientCareReport)`. The
`PatientCareReport` element carries a required `UUID` attribute.

`PatientCareReport`'s children are an `xs:sequence` - a FIXED order, not a set.
Emit them in exactly this order, omitting only the ones marked optional:

  eRecord, eResponse, eDispatch, eCrew(optional), eTimes, ePatient, ePayment,
  eScene, eSituation, eInjury, eArrest, eHistory, eNarrative(optional), eVitals,
  eLabs(optional), eExam(optional), eProtocols, eMedications, eProcedures,
  eAirway(optional), eDevice(optional), eDisposition, eOutcome,
  eCustomResults(optional), eOther(optional)

Elements within each section are also ordered sequences. Repeating groups
(eVitals.VitalGroup, eMedications.MedicationGroup, eProcedures.ProcedureGroup)
may appear more than once.

`eMedications.03` requires a `CodeType` attribute: `9924003` for RxNorm codes,
`9924005` for SNOMED-CT codes.

## Output contract

Return ONLY the XML document, wrapped between the markers `<xml>` and `</xml>`.
No prose, no markdown fences, no commentary. The caller extracts your output with
a plain string split on those markers.
"""


@dataclass
class Exemplar:
    name: str
    profile_json: str
    xml: str

    def to_prompt_block(self) -> str:
        return (
            f"### Worked example: {self.name}\n\n"
            f"Input profile:\n{self.profile_json}\n\n"
            f"Correct output:\n{MARKER_OPEN}\n{self.xml}\n{MARKER_CLOSE}\n"
        )


def load_exemplars(directory: Path = EXEMPLAR_DIR, limit: int | None = None) -> list[Exemplar]:
    """Load (scenario, XML) pairs. Each pair is a `<name>.yaml` + `<name>.xml`."""
    exemplars = []
    for scenario_path in sorted(directory.glob("*.yaml")):
        xml_path = scenario_path.with_suffix(".xml")
        if not xml_path.exists():
            continue
        scenario = Scenario.from_file(scenario_path)
        exemplars.append(
            Exemplar(
                name=scenario.name,
                profile_json=yaml.safe_dump(scenario.to_json(), sort_keys=False).strip(),
                xml=xml_path.read_text(encoding="utf-8").strip(),
            )
        )
    return exemplars[:limit] if limit else exemplars


def build_system(
    registry: Registry,
    base: str,
    exemplars: list[Exemplar],
) -> str:
    """The cacheable block: rules, catalogue, and any worked examples."""
    parts = [base, STRUCTURAL_RULES, build_code_catalogue(registry, load_fieldplan())]
    if exemplars:
        parts.append(
            "## Worked examples\n\n"
            "Each shows an input profile and the finished document it should produce.\n"
        )
        parts.extend(e.to_prompt_block() for e in exemplars)
    return "\n\n".join(parts)


def extract_xml(text: str) -> str:
    from .api_client import OutputContractError

    if MARKER_OPEN not in text or MARKER_CLOSE not in text:
        raise OutputContractError("response did not contain <xml>...</xml> markers", text)
    return text.split(MARKER_OPEN, 1)[1].split(MARKER_CLOSE, 1)[0].strip()


def generate_direct(
    client: ApiClient,
    scenario: Scenario,
    profile: Profile,
    config: ProfileConfig,
    registry: Registry,
    base_system: str,
    exemplars: list[Exemplar] | None = None,
) -> bytes:
    """One call, XML straight out of the model."""
    exemplars = exemplars or []
    system = build_system(registry, base_system, exemplars)
    raw = client.complete(
        system,
        narrative_instruction_text(profile, config),
        scenario.to_prompt_block()
        + "\n\nReturn the complete XML document between <xml> and </xml> markers.",
        effort=profile.effort,
    )
    return extract_xml(raw).encode("utf-8")
