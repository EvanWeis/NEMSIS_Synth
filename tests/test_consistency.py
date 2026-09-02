"""Cross-field consistency: timestamps and section applicability.

The downstream QA tool checks cross-field consistency, so an inconsistency the
*generator* introduced would fire its checks on an artefact rather than on
anything the fixture is meant to exercise. These are the two places the generator
could introduce one on its own.
"""

from datetime import datetime

from lxml import etree

from nemsis_gen.applicability import NOT_APPLICABLE, apply_not_applicable
from nemsis_gen.generate import DEFAULT_TEMPLATE, apply_timeline, load_fieldplan
from nemsis_gen.render import render_dataset, value_tree_from_document
from nemsis_gen.schema_model import load_model
from nemsis_gen.timeline import TIME_FIELDS, build_timeline, format_timestamp
from nemsis_gen.validate import NEMSIS_NS, validate_bytes

NS = f"{{{NEMSIS_NS}}}"
START = datetime.fromisoformat("2026-03-14T02:10:00+00:00")


def _tree(model):
    return value_tree_from_document(DEFAULT_TEMPLATE.read_bytes(), model=model)


def test_timestamp_format_matches_the_schema_type():
    assert format_timestamp(START) == "2026-03-14T02:10:00+00:00"


def test_offsets_out_of_order_are_clamped_forward_not_rejected():
    """A sloppy model response should degrade to a tight timeline, not an invalid one."""
    timeline = build_timeline(
        START, {"arrived_on_scene": 20, "arrived_at_patient": 5, "left_scene": 3}
    )
    assert timeline.offsets["arrived_at_patient"] == 20
    assert timeline.offsets["left_scene"] == 20


def test_timeline_is_monotonic_for_arbitrary_garbage():
    timeline = build_timeline(START, {stage: -99 for _f, stage in TIME_FIELDS})
    values = [timeline.offsets[stage] for _f, stage in TIME_FIELDS]
    assert values == sorted(values)


def test_intervention_times_are_clamped_inside_the_incident_window():
    timeline = build_timeline(START, None)
    early = timeline.at_minute(-500)
    late = timeline.at_minute(99999)
    assert early == timeline.at("arrived_at_patient")
    assert late == timeline.at("transfer_of_care")


def test_rendered_etimes_are_ordered_and_land_in_the_document(registry):
    model = load_model()
    sections, demographic, _uuid = _tree(model)
    clinical = {
        "incident_start": "2026-03-14T02:10:00",
        "timeline_offsets": {"arrived_on_scene": 9, "left_scene": 26},
        "vitals": [{"minute": 12}, {"minute": 20}],
    }
    apply_timeline(sections, clinical, load_fieldplan(), model)
    xml, _ = render_dataset(sections, demographic, model=model)

    root = etree.fromstring(xml)
    stamps = []
    for field, _stage in TIME_FIELDS:
        element = root.find(f".//{NS}{field}")
        assert element is not None, field
        stamps.append(element.text)

    assert stamps == sorted(stamps), stamps
    assert stamps[0].startswith("2026-03-14T02:10")
    assert validate_bytes(xml, registry=registry).ok


def test_non_injury_call_marks_einjury_not_applicable(registry):
    model = load_model()
    sections, demographic, _uuid = _tree(model)
    marked = apply_not_applicable(
        sections, {"is_injury": False, "is_cardiac_arrest": False}, model, registry
    )
    assert set(marked) == {"eInjury", "eArrest"}

    xml, _ = render_dataset(sections, demographic, model=model)
    root = etree.fromstring(xml)

    cause = root.find(f".//{NS}eInjury.01")
    assert cause.get("NV") == NOT_APPLICABLE
    assert cause.get("{http://www.w3.org/2001/XMLSchema-instance}nil") == "true"
    assert not (cause.text or "").strip()

    # The template's inherited cause-of-injury code must be gone, not merely hidden.
    assert b"T56.0" not in xml
    assert validate_bytes(xml, registry=registry).ok


def test_injury_call_keeps_its_einjury_content(registry):
    model = load_model()
    sections, demographic, _uuid = _tree(model)
    before = sections["eInjury"]
    marked = apply_not_applicable(sections, {"is_injury": True}, model, registry)
    assert "eInjury" not in marked
    assert sections["eInjury"] == before
