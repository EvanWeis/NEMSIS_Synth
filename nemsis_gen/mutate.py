"""Deterministic corruptions for the invalid-by-design quality tiers.

Breakage is applied by code, after rendering, rather than asked of the model.
That matters for the acceptance criterion: a file has to fail in a *specific,
documented* way, and the manifest has to record why. Prompting a model to "make
it invalid" gives you neither guarantee.

Every mutation returns a description of exactly what it did, which becomes the
expected-failure assertion in the manifest.
"""

from __future__ import annotations

import random
from collections.abc import Callable

from lxml import etree

from .valuesets import Registry

NEMSIS_NS = "http://www.nemsis.org"


class MutationError(RuntimeError):
    """The document did not contain what the mutation needed to corrupt."""


def _parse(data: bytes) -> etree._Element:
    return etree.fromstring(data)


def _serialise(root: etree._Element) -> bytes:
    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8")


def _pcr(root: etree._Element) -> etree._Element:
    pcr = root.find(f"{{{NEMSIS_NS}}}Header/{{{NEMSIS_NS}}}PatientCareReport")
    if pcr is None:
        raise MutationError("no PatientCareReport in document")
    return pcr


def structural(
    data: bytes, registry: Registry, rng: random.Random, **_: object
) -> tuple[bytes, str]:
    """Violate the PatientCareReport xs:sequence by swapping two sections."""
    root = _parse(data)
    pcr = _pcr(root)
    sections = list(pcr)
    if len(sections) < 2:
        raise MutationError("need at least two sections to reorder")

    index = rng.randrange(len(sections) - 1)
    first, second = sections[index], sections[index + 1]
    pcr.remove(first)
    second.addnext(first)
    names = (
        etree.QName(first).localname,
        etree.QName(second).localname,
    )
    return _serialise(root), f"swapped element order: {names[1]} now precedes {names[0]}"


def drop_required_leaves(
    data: bytes, registry: Registry, rng: random.Random, count: int = 3, **_: object
) -> tuple[bytes, str]:
    """Remove leaves the schema marks Mandatory or Required."""
    root = _parse(data)
    pcr = _pcr(root)
    prefix = f"{{{NEMSIS_NS}}}"

    candidates = []
    for element in pcr.iter():
        if len(element):  # groups are not leaves
            continue
        number = str(element.tag).replace(prefix, "")
        definition = registry.fields.get(number)
        if definition and definition.usage in {"Mandatory", "Required"}:
            candidates.append((number, element))
    if not candidates:
        raise MutationError("no required leaves found to drop")

    chosen = rng.sample(candidates, min(count, len(candidates)))
    for _number, element in chosen:
        element.getparent().remove(element)
    dropped = ", ".join(number for number, _ in chosen)
    return _serialise(root), f"removed required elements: {dropped}"


def illegal_codes(
    data: bytes, registry: Registry, rng: random.Random, count: int = 2, **_: object
) -> tuple[bytes, str]:
    """Replace enumerated values with codes outside their national value set.

    The substitute keeps the 7-digit shape so the failure is a value-set
    violation, not a type error - that is the distinction the tier exists to test.
    """
    root = _parse(data)
    pcr = _pcr(root)
    prefix = f"{{{NEMSIS_NS}}}"

    candidates = []
    for element in pcr.iter():
        if len(element) or not (element.text or "").strip():
            continue
        number = str(element.tag).replace(prefix, "")
        definition = registry.fields.get(number)
        if definition and definition.defined_list is None and registry.values_for(number):
            candidates.append((number, element))
    if not candidates:
        raise MutationError("no enumerated leaves found to corrupt")

    changes = []
    for number, element in rng.sample(candidates, min(count, len(candidates))):
        original = element.text
        legal = {value.code for value in registry.values_for(number)}
        replacement = next(
            (
                candidate
                for candidate in (str(int(original) + offset) for offset in range(1, 200))
                if candidate not in legal
            )
            if original.isdigit()
            else iter(["9999999"]),
            "9999999",
        )
        element.text = replacement
        changes.append(f"{number}: {original} -> {replacement}")
    return _serialise(root), "illegal codes injected: " + "; ".join(changes)


def malform(data: bytes, registry: Registry, rng: random.Random, **_: object) -> tuple[bytes, str]:
    """Break XML syntax itself, to exercise the parser gate rather than the schema."""
    text = data.decode("utf-8")
    styles = [
        ("unclosed tag", lambda t: t.replace("</eRecord>", "", 1)),
        ("unescaped ampersand", lambda t: t.replace("<eNarrative.01>", "<eNarrative.01>A & B ", 1)),
        ("mismatched closing tag", lambda t: t.replace("</eDispatch>", "</eDispatchX>", 1)),
    ]
    rng.shuffle(styles)
    for name, apply in styles:
        mutated = apply(text)
        if mutated != text:
            return mutated.encode("utf-8"), f"malformed XML: {name}"
    raise MutationError("no malformation anchor found in document")


MUTATIONS: dict[str, Callable[..., tuple[bytes, str]]] = {
    "structural": structural,
    "drop_required_leaves": drop_required_leaves,
    "illegal_codes": illegal_codes,
    "malform": malform,
}


def apply_mutation(
    name: str, data: bytes, registry: Registry, params: dict, seed: int | None = None
) -> tuple[bytes, str]:
    if name not in MUTATIONS:
        raise KeyError(f"unknown mutation {name!r}; known: {', '.join(sorted(MUTATIONS))}")
    return MUTATIONS[name](data, registry, random.Random(seed), **params)
