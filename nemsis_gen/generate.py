"""Two-stage generation: clinical intent, then code selection, then rendering.

Stage A asks the model for a *clinical* account of the encounter in plain
language - no codes, no XML. Stage B hands back each field's legal value set and
asks it to choose. The renderer then places the chosen values into the document.

The model therefore never recalls a NEMSIS code from memory; it selects one from
a table that came out of the schema. That is the whole point of the split: code
recall is the failure mode that produces plausible, wrong, hard-to-spot data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import field as dc_field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .api_client import ApiClient, extract_json_block
from .profiles import Profile, ProfileConfig, load_system_base
from .render import render_dataset, value_tree_from_document
from .scenario import Scenario
from .schema_model import Node, SchemaModel, load_model
from .valuesets import Registry

FIELDPLAN_PATH = Path(__file__).resolve().parent / "prompts" / "fieldplan.yaml"

# NoRepeat is the right base: the Nils / PNs / ElementsRepeat series exercise
# null flavours and repeat cardinality, which belong in validation fixtures
# rather than in a template we overlay clinical content onto.
DEFAULT_TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "reference"
    / "samples"
    / "ems_xml"
    / "EMSDataset-NoRepeat-1.xml"
)

MAX_CANDIDATES = 200


@dataclass
class FieldPlan:
    singletons: dict[str, str]
    repeating_singletons: dict[str, str]
    literals: dict[str, str]
    groups: dict[str, dict]

    def coded_fields(self) -> list[str]:
        fields = list(self.singletons) + list(self.repeating_singletons)
        for spec in self.groups.values():
            fields.extend(spec.get("coded", {}))
        return fields


@lru_cache(maxsize=2)
def load_fieldplan(path: Path = FIELDPLAN_PATH) -> FieldPlan:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return FieldPlan(
        singletons=data.get("singletons") or {},
        repeating_singletons=data.get("repeating_singletons") or {},
        literals=data.get("literals") or {},
        groups=data.get("groups") or {},
    )


def find_path(model: SchemaModel, field: str) -> list[str] | None:
    """Locate a field number in the PatientCareReport tree.

    Field numbers are unique, so the path is derivable rather than something to
    maintain by hand alongside the schema.
    """

    def walk(node: Node, trail: list[str]) -> list[str] | None:
        for child in node.children:
            if child.name == field:
                return [*trail, child.name]
            found = walk(child, [*trail, child.name])
            if found:
                return found
        return None

    return walk(model.patient_care_report, [])


def build_code_catalogue(registry: Registry, plan: FieldPlan) -> str:
    """The cacheable block: every value set the model may choose from.

    Identical on every call in a run, so it belongs in the cached system block
    rather than in the per-record message.
    """
    lines = [
        "## Code catalogue",
        "",
        "Choose codes ONLY from these lists. Never invent a code, and never use a",
        "code from one field's list for another field.",
        "",
    ]
    for field in plan.coded_fields():
        values = registry.values_for(field)
        definition = registry.fields[field]
        if not values:
            continue
        lines.append(f"### {field} - {definition.name}")
        if definition.defined_list:
            dl = registry.defined_lists[definition.defined_list]
            lines.append(f"({dl.name} defined list, source: {', '.join(dl.source_vocabularies)})")
        for value in values[:MAX_CANDIDATES]:
            category = f" [{value.category}]" if value.category else ""
            lines.append(f"- {value.code} = {value.label}{category}")
        lines.append("")
    return "\n".join(lines)


STAGE_A_INSTRUCTIONS = """
## Your task (stage 1 of 2: clinical content)

Describe the encounter as structured clinical facts in plain language. Do NOT use
NEMSIS codes anywhere - a later step maps your wording onto the code tables.

Return this JSON shape between the markers:

{
  "dispatch_reason": "...",
  "type_of_service_requested": "...",
  "unit_transport_capability": "...",
  "incident_location_type": "...",
  "chief_complaint_anatomic_location": "...",
  "chief_complaint_organ_system": "...",
  "primary_symptom": "...",
  "other_associated_symptoms": ["...", "..."],
  "primary_impression": "...",
  "secondary_impressions": ["..."],
  "initial_patient_acuity": "...",
  "final_patient_acuity": "...",
  "gender": "...",
  "age": "64",
  "ems_transport_method": "...",
  "type_of_destination": "...",
  "level_of_care_provided": "...",
  "vitals": [
    {"sbp": "138", "heart_rate": "104", "spo2": "89", "respiratory_rate": "28",
     "pain_score": "0", "responsiveness": "alert"}
  ],
  "medications": [
    {"medication": "albuterol", "dosage": "2.5", "dosage_units": "milligrams",
     "route": "nebulized inhalation", "response": "improved"}
  ],
  "procedures": [
    {"procedure": "IV access", "attempts": "1", "successful": "yes",
     "response": "improved"}
  ],
  "narrative": "..."
}

Give at least two sets of vitals. Include only medications and procedures that
were actually performed in this scenario.
"""

STAGE_B_INSTRUCTIONS = """
## Your task (stage 2 of 2: code selection)

You are given the clinical account you produced and the fields that need NEMSIS
codes. For each one, choose the single best code from that field's list in the
code catalogue above. If nothing fits well, choose the closest available code -
do not invent one, and do not leave a field out.

Return JSON between the markers with exactly this shape:

{
  "singletons": {"eDispatch.01": "2301045"},
  "repeating_singletons": {"eSituation.10": ["...", "..."]},
  "groups": {
    "eVitals.VitalGroup": [{"eVitals.26": "..."}],
    "eMedications.MedicationGroup": [{"eMedications.03": "435"}],
    "eProcedures.ProcedureGroup": [{"eProcedures.03": "..."}]
  }
}

The lists under "groups" must have exactly the same number of entries, in the
same order, as the corresponding lists in the clinical account.
"""


def narrative_instruction(profile: Profile, config: ProfileConfig) -> str:
    return (
        f"## Quality profile: {profile.name}\n\n"
        f"{profile.description}\n\n"
        f"### Narrative quality target: {profile.narrative_quality} of 5\n\n"
        f"{config.rubric_for(profile.narrative_quality)}\n\n"
        "The narrative must land at exactly this level. Every other part of the "
        "record stays clinically coherent and schema-valid regardless of the "
        "narrative target - documentation quality is the only variable this dial "
        "controls."
    )


@dataclass
class GenerationResult:
    xml: bytes
    clinical: dict
    codes: dict
    unknown_codes: list[str] = dc_field(default_factory=list)
    render_report: Any = None


def _record_selection(registry: Registry, field: str, code: str, unknown: list[str]) -> None:
    """Never trust a selection blindly - a code off the table is recorded."""
    values = registry.values_for(field)
    if values and not any(v.code == code for v in values):
        unknown.append(f"{field}={code}")


def _leaf_value(registry: Registry, field: str, code: str) -> Any:
    """Attach the CodeType attribute where the schema requires one."""
    definition = registry.fields.get(field)
    if definition and definition.defined_list:
        for value in registry.values_for(field):
            if value.code == code and value.code_type:
                return {"value": code, "attrs": {"CodeType": value.code_type}}
    return code


def _place(tree: dict, path: list[str], value: Any) -> None:
    """Overlay a value at a schema path, creating intermediate groups as needed."""
    cursor: Any = tree
    for name in path[:-1]:
        nxt = cursor.get(name)
        if isinstance(nxt, list):
            nxt = nxt[0] if nxt else {}
        if not isinstance(nxt, dict):
            nxt = {}
        cursor[name] = nxt
        cursor = nxt
    cursor[path[-1]] = value


def _relative_path(model: SchemaModel, field: str, group_path: list[str]) -> list[str]:
    inner = find_path(model, field)
    return inner[len(group_path) :] if inner else [field]


def apply_selections(
    sections: dict,
    clinical: dict,
    codes: dict,
    plan: FieldPlan,
    model: SchemaModel,
    registry: Registry,
) -> list[str]:
    """Overlay stage A literals and stage B codes onto the template value tree."""
    unknown: list[str] = []

    for field, code in (codes.get("singletons") or {}).items():
        path = find_path(model, field)
        if not path or not code:
            continue
        _record_selection(registry, field, code, unknown)
        _place(sections, path, _leaf_value(registry, field, code))

    for field, values in (codes.get("repeating_singletons") or {}).items():
        path = find_path(model, field)
        if not path or not values:
            continue
        for code in values:
            _record_selection(registry, field, code, unknown)
        _place(sections, path, [_leaf_value(registry, field, c) for c in values])

    for field, key in plan.literals.items():
        path = find_path(model, field)
        value = clinical.get(key)
        if path and value not in (None, ""):
            _place(sections, path, str(value))

    for group_name, spec in plan.groups.items():
        group_path = find_path(model, group_name)
        items = clinical.get(spec["intent"]) or []
        selections = (codes.get("groups") or {}).get(group_name) or []
        if not group_path or not items:
            continue

        cursor: Any = sections
        for name in group_path:
            cursor = cursor.get(name, {}) if isinstance(cursor, dict) else {}
        template_item = (cursor[0] if isinstance(cursor, list) and cursor else cursor) or {}

        rendered = []
        for index, item in enumerate(items):
            entry = json.loads(json.dumps(template_item))  # deep copy of the template row
            chosen = selections[index] if index < len(selections) else {}
            for field, code in chosen.items():
                if not code:
                    continue
                _record_selection(registry, field, code, unknown)
                _place(
                    entry,
                    _relative_path(model, field, group_path),
                    _leaf_value(registry, field, code),
                )
            for field, key in (spec.get("literal") or {}).items():
                value = item.get(key)
                if value in (None, ""):
                    continue
                _place(entry, _relative_path(model, field, group_path), str(value))
            rendered.append(entry)

        _place(sections, group_path, rendered)

    return unknown


def build_cached_system(registry: Registry, plan: FieldPlan | None = None) -> str:
    plan = plan or load_fieldplan()
    return "\n\n".join([load_system_base(), build_code_catalogue(registry, plan)])


def generate_record(
    client: ApiClient,
    scenario: Scenario,
    profile: Profile,
    config: ProfileConfig,
    registry: Registry,
    template: Path = DEFAULT_TEMPLATE,
    model: SchemaModel | None = None,
) -> GenerationResult:
    model = model or load_model()
    plan = load_fieldplan()

    cached_system = build_cached_system(registry, plan)
    profile_block = narrative_instruction(profile, config)

    stage_a_raw = client.complete(
        cached_system,
        profile_block + "\n" + STAGE_A_INSTRUCTIONS,
        scenario.to_prompt_block()
        + "\n\nReturn the clinical JSON between <json> and </json> markers.",
        effort=profile.effort,
    )
    clinical = json.loads(extract_json_block(stage_a_raw))

    coded_request = {
        "clinical_account": clinical,
        "fields_to_code": {
            "singletons": plan.singletons,
            "repeating_singletons": plan.repeating_singletons,
            "groups": {name: spec.get("coded", {}) for name, spec in plan.groups.items()},
        },
    }
    stage_b_raw = client.complete(
        cached_system,
        profile_block + "\n" + STAGE_B_INSTRUCTIONS,
        json.dumps(coded_request, indent=1)
        + "\n\nReturn the code selections between <json> and </json> markers.",
        effort="low",  # selection is a lookup, not a creative act
    )
    codes = json.loads(extract_json_block(stage_b_raw))

    sections, demographic, _uuid = value_tree_from_document(template.read_bytes(), model=model)
    unknown = apply_selections(sections, clinical, codes, plan, model, registry)
    xml, report = render_dataset(sections, demographic, model=model)

    return GenerationResult(
        xml=xml,
        clinical=clinical,
        codes=codes,
        unknown_codes=unknown,
        render_report=report,
    )
