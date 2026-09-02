"""Mark sections Not Applicable when the encounter did not involve them.

Without this, a section outside the field plan is inherited wholesale from the
template - so a COPD exacerbation arrives carrying the template's cause-of-injury
code and a full cardiac-arrest block. Schema-valid, and clinically nonsense.

Cross-field consistency checking is exactly the thing that catches it, so a
fixture set built this way would fire the checker on artefacts of the generator
rather than on anything the record is meant to test.

NEMSIS's own answer is the null flavour: `<eInjury.01 xsi:nil="true"
NV="7701001"/>`. This module applies it to whole sections, driven by two booleans
the clinical stage already knows.
"""

from __future__ import annotations

from typing import Any

from .schema_model import Node, SchemaModel
from .valuesets import Registry

NOT_APPLICABLE = "7701001"
NOT_RECORDED = "7701003"

# Sections that only apply under a condition the clinical account reports.
CONDITIONAL_SECTIONS: dict[str, str] = {
    "eInjury": "is_injury",
    "eArrest": "is_cardiac_arrest",
}


def nil_value(nv_code: str = NOT_APPLICABLE) -> dict:
    """A null-flavoured leaf: empty, xsi:nil, with a Not Value attribute."""
    return {"value": "", "attrs": {"NV": nv_code}, "nil": True}


def _nil_tree(node: Node, registry: Registry) -> Any:
    """Rebuild a section as null flavours, keeping only what the schema requires.

    Optional children are dropped rather than nilled - an empty optional element
    is noise, and some do not accept a Not Value at all.
    """
    if not node.is_group:
        definition = registry.fields.get(node.name)
        if definition is None or not definition.nv_types:
            return None
        return nil_value()

    out: dict[str, Any] = {}
    for child in node.children:
        if not child.required:
            continue
        rendered = _nil_tree(child, registry)
        if rendered is not None:
            out[child.name] = rendered
    return out or None


def apply_not_applicable(
    sections: dict,
    clinical: dict,
    model: SchemaModel,
    registry: Registry,
) -> list[str]:
    """Nil out conditional sections the encounter did not involve.

    Returns the section names that were marked Not Applicable, for the manifest.
    """
    marked: list[str] = []
    pcr = model.patient_care_report

    for section_name, flag in CONDITIONAL_SECTIONS.items():
        if _truthy(clinical.get(flag)):
            continue  # the encounter did involve it; leave the generated content
        node = pcr.child(section_name)
        if node is None:
            continue
        nilled = _nil_tree(node, registry)
        if nilled:
            sections[section_name] = nilled
            marked.append(section_name)

    return marked


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1"}
    return bool(value)
