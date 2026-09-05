import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


INPUT_FILE = Path("events.json")
OUTPUT_FILE = Path("metlife-stadium-calendar.ics")

CALENDAR_NAME = "MetLife Stadium Events"
CALENDAR_DESCRIPTION = (
    "Upcoming events at MetLife Stadium, excluding New York Giants home games."
)

DEFAULT_EVENT_DURATION_HOURS = 4

# Keep DTSTAMP deterministic so the .ics file does not change every day
# merely because the GitHub Action ran again.
DTSTAMP = "20260905T120000Z"


def escape_ics_text(value):
    if value is None:
        return ""

    value = str(value)

    return (
        value
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def fold_ics_line(line):
    encoded = line.encode("utf-8")

    if len(encoded) <= 75:
        return line

    output = []
    current = ""

    for char in line:
        candidate = current + char

        if len(candidate.encode("utf-8")) > 75:
            output.append(current)
            current = " " + char
        else:
            current = candidate

    if current:
        output.append(current)

    return "\r\n".join(output)


def parse_utc_datetime(value):
    if not value:
        return None

    value = value.strip()

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    parsed = datetime.fromisoformat(value)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def format_utc_datetime(value):
    return value.strftime("%Y%m%dT%H%M%SZ")


def format_date(value):
    return value.replace("-", "")


def build_location(event):
    return "MetLife Stadium"


def build_description(event):
    parts = [
        "MetLife Stadium event.",
    ]

    classifications = event.get("classifications", [])
    categories = []

    for classification in classifications:
        for key in ("segment", "genre", "subGenre"):
            value = classification.get(key)

            if value and value not in categories:
                categories.append(value)

    if categories:
        parts.append(
            "Category: " + " / ".join(categories) + "."
        )

    url = event.get("url")

    if url:
        parts.append("Source: " + url)

    return "\n\n".join(parts)


def should_skip_event(event):
    status = (event.get("status") or "").casefold()

    if status in {"cancelled", "canceled"}:
        return True

    if not event.get("id"):
        return True

    if not event.get("name"):
        return True

    return False


def build_event_lines(event):
    event_id = event["id"]
    name = event["name"]
    start = event.get("start", {})

    local_date = start.get("localDate")
    utc_datetime = start.get("dateTime")

    time_tba = bool(start.get("timeTBA"))
    date_tba = bool(start.get("dateTBA"))
    date_tbd = bool(start.get("dateTBD"))
    no_specific_time = bool(start.get("noSpecificTime"))

    lines = [
        "BEGIN:VEVENT",
        f"UID:metlife-{escape_ics_text(event_id)}@github-calendar",
        f"DTSTAMP:{DTSTAMP}",
        f"SUMMARY:{escape_ics_text(name)}",
        f"LOCATION:{escape_ics_text(build_location(event))}",
        f"DESCRIPTION:{escape_ics_text(build_description(event))}",
    ]

    event_url = event.get("url")

    if event_url:
        lines.append(f"URL:{escape_ics_text(event_url)}")

    has_specific_time = (
        utc_datetime
        and not time_tba
        and not no_specific_time
        and not date_tba
        and not date_tbd
    )

    if has_specific_time:
        start_datetime = parse_utc_datetime(utc_datetime)

        if start_datetime:
            end_datetime = start_datetime + timedelta(
                hours=DEFAULT_EVENT_DURATION_HOURS
            )

            lines.append(
                f"DTSTART:{format_utc_datetime(start_datetime)}"
            )
            lines.append(
                f"DTEND:{format_utc_datetime(end_datetime)}"
            )

    elif local_date:
        start_date = datetime.strptime(
            local_date,
            "%Y-%m-%d",
        ).date()

        end_date = start_date + timedelta(days=1)

        lines.append(
            f"DTSTART;VALUE=DATE:{format_date(start_date.isoformat())}"
        )
        lines.append(
            f"DTEND;VALUE=DATE:{format_date(end_date.isoformat())}"
        )

    else:
        return None

    lines.append("END:VEVENT")

    return lines


def main():
    try:
        if not INPUT_FILE.exists():
            raise RuntimeError(
                f"{INPUT_FILE} does not exist. "
                "Run fetch_events.py first."
            )

        with INPUT_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:
            payload = json.load(file)

        events = payload.get("events", [])

        calendar_lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Matt Malinconico//MetLife Stadium Calendar//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            f"X-WR-CALNAME:{escape_ics_text(CALENDAR_NAME)}",
            "X-WR-TIMEZONE:America/New_York",
            (
                "X-WR-CALDESC:"
                f"{escape_ics_text(CALENDAR_DESCRIPTION)}"
            ),
            "REFRESH-INTERVAL;VALUE=DURATION:P1D",
            "X-PUBLISHED-TTL:P1D",
        ]

        included_count = 0
        skipped_count = 0

        def sort_key(event):
            start = event.get("start", {})

            return (
                start.get("dateTime")
                or start.get("localDate")
                or "9999-12-31"
            )

        for event in sorted(events, key=sort_key):
            if should_skip_event(event):
                skipped_count += 1
                continue

            event_lines = build_event_lines(event)

            if not event_lines:
                print(
                    f"Skipping event with no usable date: "
                    f"{event.get('name')}"
                )
                skipped_count += 1
                continue

            calendar_lines.extend(event_lines)
            included_count += 1

        calendar_lines.append("END:VCALENDAR")

        folded_lines = [
            fold_ics_line(line)
            for line in calendar_lines
        ]

        calendar_text = "\r\n".join(folded_lines) + "\r\n"

        OUTPUT_FILE.write_text(
            calendar_text,
            encoding="utf-8",
            newline="",
        )

        print(f"Events written to calendar: {included_count}")
        print(f"Events skipped: {skipped_count}")
        print(f"Wrote {OUTPUT_FILE}")

    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
