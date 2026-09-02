"""Incident timestamps, derived in code from relative offsets.

Cross-field consistency checks read timestamps hard: dispatch must precede en
route, which must precede arrival, and every vital sign, medication and procedure
must fall inside the incident window. Asking a model for absolute ISO timestamps
and hoping they come back monotonic is the same mistake as asking it to order XML
elements - so the model supplies *offsets in minutes* and this module turns them
into timestamps that are ordered by construction.

The stage ordering below is the NEMSIS eTimes sequence. An offset that arrives out
of order is clamped forward to its predecessor rather than rejected, so a sloppy
model response degrades into a tight timeline instead of an invalid one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# eTimes field -> ordered stage name the model supplies an offset for.
TIME_FIELDS: list[tuple[str, str]] = [
    ("eTimes.01", "psap_call"),
    ("eTimes.02", "dispatch_notified"),
    ("eTimes.03", "unit_notified"),
    ("eTimes.05", "en_route"),
    ("eTimes.06", "arrived_on_scene"),
    ("eTimes.07", "arrived_at_patient"),
    ("eTimes.09", "left_scene"),
    ("eTimes.11", "arrived_at_destination"),
    ("eTimes.12", "transfer_of_care"),
    ("eTimes.13", "back_in_service"),
]

# Fallback offsets (minutes from PSAP call) for a routine transport, used when the
# model omits a stage. Chosen to be plausible rather than fast.
DEFAULT_OFFSETS: dict[str, int] = {
    "psap_call": 0,
    "dispatch_notified": 1,
    "unit_notified": 2,
    "en_route": 3,
    "arrived_on_scene": 9,
    "arrived_at_patient": 11,
    "left_scene": 26,
    "arrived_at_destination": 38,
    "transfer_of_care": 45,
    "back_in_service": 58,
}


@dataclass
class Timeline:
    """Absolute timestamps for one incident, guaranteed monotonic."""

    start: datetime
    offsets: dict[str, int]

    def at(self, stage: str) -> str:
        return format_timestamp(self.start + timedelta(minutes=self.offsets[stage]))

    def at_minute(self, minute: float) -> str:
        """A timestamp for an intervention, clamped inside the incident window."""
        low = self.offsets["arrived_at_patient"]
        high = self.offsets["transfer_of_care"]
        return format_timestamp(self.start + timedelta(minutes=min(max(minute, low), high)))

    def field_values(self) -> dict[str, str]:
        return {field: self.at(stage) for field, stage in TIME_FIELDS}


def format_timestamp(moment: datetime) -> str:
    """NEMSIS DateTimeType: ISO 8601 with a numeric UTC offset, seconds precision."""
    return moment.strftime("%Y-%m-%dT%H:%M:%S") + moment.strftime("%z")[:3] + ":00"


def build_timeline(
    start: datetime,
    raw_offsets: dict | None = None,
) -> Timeline:
    """Normalise model-supplied stage offsets into a monotonic timeline."""
    raw_offsets = raw_offsets or {}
    offsets: dict[str, int] = {}
    previous = 0

    for _field, stage in TIME_FIELDS:
        try:
            value = int(float(raw_offsets.get(stage, DEFAULT_OFFSETS[stage])))
        except (TypeError, ValueError):
            value = DEFAULT_OFFSETS[stage]
        # Monotonic by construction: a stage can never precede the one before it.
        previous = max(value, previous)
        offsets[stage] = previous

    return Timeline(start=start, offsets=offsets)
