"""Protect published feeds from successful-but-incomplete Ticketmaster results."""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import generate_calendar as calendar


def validate_source(payload, previous_all_feed):
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError("Ticketmaster event payload is missing or invalid")
    events = payload["events"]
    ids = [e.get("id") for e in events if isinstance(e, dict)]
    if len(ids) != len(events) or not all(ids) or len(set(ids)) != len(ids):
        raise ValueError("Ticketmaster events contain missing or duplicate IDs")
    if payload.get("eventCount") != len(events):
        raise ValueError("Ticketmaster event count disagrees with records")

    now = datetime.now(ZoneInfo("America/New_York"))
    previous = []
    if Path(previous_all_feed).exists():
        for block in calendar.read_existing_event_blocks(Path(previous_all_feed)):
            start = calendar.existing_event_start(block)
            if start and (
                start["local_date"] > now.date()
                if start["all_day"] else start["datetime"] > now
            ):
                uid = calendar.get_property_value(block, "UID")
                if uid and uid.startswith("metlife-all-"):
                    previous.append(
                        uid.removeprefix("metlife-all-").removesuffix("@github-calendar")
                    )

    known = set(ids)
    missing = [eid for eid in previous if eid not in known]
    # Isolated omissions use the 48-hour ICS cache in the generator.
    # An abrupt disappearance of half the future schedule fails closed.
    if (
        len(previous) >= 5
        and len(missing) >= 3
        and len(missing) / len(previous) >= 0.50
    ):
        raise RuntimeError(
            "Ticketmaster unexpectedly omitted "
            f"{len(missing)} of {len(previous)} previously published future "
            "events. Refusing to publish potentially incomplete feeds."
        )
    print(
        f"Source integrity check passed: {len(events)} events; "
        f"{len(missing)} temporarily missing future IDs"
    )


if __name__ == "__main__":
    payload = json.loads(Path("events.json").read_text(encoding="utf-8"))
    validate_source(payload, "metlife-stadium-all-events.ics")
