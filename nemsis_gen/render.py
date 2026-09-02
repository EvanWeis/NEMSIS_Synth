"""Render a NEMSIS EMSDataSet document from a plain value tree.

The generator never asks the model for XML. It asks for values, and this module
places them into the document in schema order. Element ordering, namespacing and
the ``xsi:schemaLocation`` boilerplate therefore cannot be got wrong by accident
- only deliberately, by the mutations in :mod:`nemsis_gen.mutate`.

Value tree shape mirrors the schema tree::

    {"eRecord": {"eRecord.01": "4xN",
                 "eRecord.SoftwareApplicationGroup": {"eRecord.02": "c", ...}},
     "eMedications": {"eMedications.MedicationGroup": [{...}, {...}]}}

A leaf value is a string, a list of strings (for repeating leaves), or a dict
``{"value": "435", "attrs": {"CodeType": "9924003"}}`` when attributes are needed.
Add ``"nil": True`` for a NEMSIS null flavour - ``<eInjury.01 xsi:nil="true"
NV="7701001"/>`` - which is how a section that does not apply is expressed.
"""

from __future__ import annotations

import uuid as uuid_module
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from lxml import etree

from .schema_model import Node, SchemaModel, load_model

NEMSIS_NS = "http://www.nemsis.org"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_LOCATION = (
    "http://www.nemsis.org "
    "http://nemsis.org/media/nemsis_v3/release-3.5.0/XSDs/NEMSIS_XSDs/EMSDataSet_v3.xsd"
)


@dataclass
class RenderReport:
    """What the renderer had to skip - the honest account of a partial record."""

    unknown_keys: list[str] = dc_field(default_factory=list)
    missing_required: list[str] = dc_field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "unknown_keys": self.unknown_keys,
            "missing_required": self.missing_required,
        }


def _qname(name: str) -> str:
    return f"{{{NEMSIS_NS}}}{name}"


def _split(value: Any) -> tuple[str, dict[str, str], bool]:
    if isinstance(value, dict):
        attrs = {k: str(v) for k, v in (value.get("attrs") or {}).items()}
        return str(value.get("value", "")), attrs, bool(value.get("nil"))
    return ("" if value is None else str(value)), {}, False


def _render_node(node: Node, value: Any, parent: etree._Element, report: RenderReport) -> None:
    occurrences = value if isinstance(value, list) and node.repeats else [value]

    for occurrence in occurrences:
        if node.is_group:
            if not isinstance(occurrence, dict):
                report.unknown_keys.append(f"{node.name}: expected an object")
                continue
            element = etree.SubElement(parent, _qname(node.name))
            _render_children(node, occurrence, element, report)
        else:
            text, attrs, nil = _split(occurrence)
            element = etree.SubElement(parent, _qname(node.name))
            if text:
                element.text = text
            if nil:
                element.set(f"{{{XSI_NS}}}nil", "true")
            for key, attr_value in attrs.items():
                element.set(key, attr_value)


def _render_children(
    node: Node, values: dict, parent: etree._Element, report: RenderReport
) -> None:
    known = {child.name for child in node.children}
    for key in values:
        if key not in known and not key.startswith("_"):
            report.unknown_keys.append(f"{node.name}/{key}")

    for child in node.children:
        if child.name not in values or values[child.name] is None:
            if child.required:
                report.missing_required.append(child.name)
            continue
        _render_node(child, values[child.name], parent, report)


def render_dataset(
    sections: dict[str, Any],
    demographic_group: dict[str, Any],
    record_uuid: str | None = None,
    model: SchemaModel | None = None,
) -> tuple[bytes, RenderReport]:
    """Build a one-PCR EMSDataSet document. Returns (xml bytes, report)."""
    model = model or load_model()
    report = RenderReport()

    dataset_node = model.dataset
    header_node = dataset_node.child("Header")
    demographic_node = header_node.child("DemographicGroup")
    pcr_node = header_node.child("PatientCareReport")

    root = etree.Element(
        _qname("EMSDataSet"),
        nsmap={None: NEMSIS_NS, "xsi": XSI_NS},
        attrib={f"{{{XSI_NS}}}schemaLocation": SCHEMA_LOCATION},
    )
    header = etree.SubElement(root, _qname("Header"))

    demographic = etree.SubElement(header, _qname("DemographicGroup"))
    _render_children(demographic_node, demographic_group, demographic, report)

    pcr = etree.SubElement(header, _qname("PatientCareReport"))
    pcr.set("UUID", record_uuid or str(uuid_module.uuid4()))
    _render_children(pcr_node, sections, pcr, report)

    xml = etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    return xml, report


def extract_value_tree(root: etree._Element, node: Node) -> Any:
    """Inverse of the renderer: turn a document subtree into a value tree.

    Used to seed a generation run from an official sample, and to round-trip test
    the renderer against the reference corpus.
    """
    if not node.is_group:
        text = (root.text or "").strip()
        attrs = {k: v for k, v in root.attrib.items()}
        nil = attrs.pop(f"{{{XSI_NS}}}nil", None) == "true"
        if attrs or nil:
            return {"value": text, "attrs": attrs, "nil": nil}
        return text

    out: dict[str, Any] = {}
    for child_node in node.children:
        matches = root.findall(_qname(child_node.name))
        if not matches:
            continue
        values = [extract_value_tree(m, child_node) for m in matches]
        out[child_node.name] = values if child_node.repeats else values[0]
    return out


def value_tree_from_document(
    data: bytes, model: SchemaModel | None = None
) -> tuple[dict, dict, str]:
    """Return (sections, demographic_group, uuid) for the first PCR in a document."""
    model = model or load_model()
    root = etree.fromstring(data)
    header_node = model.dataset.child("Header")
    header = root.find(_qname("Header"))
    demographic = extract_value_tree(
        header.find(_qname("DemographicGroup")), header_node.child("DemographicGroup")
    )
    pcr_element = header.find(_qname("PatientCareReport"))
    sections = extract_value_tree(pcr_element, header_node.child("PatientCareReport"))
    return sections, demographic, pcr_element.get("UUID")
