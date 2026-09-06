import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


INPUT_FILE = Path("events.json")

STANDARD_OUTPUT_FILE = Path("metlife-stadium-calendar.ics")
ALL_EVENTS_OUTPUT_FILE = Path("metlife-stadium-all-events.ics")

STANDARD_CALENDAR_NAME = "MetLife Stadium Events"
STANDARD_CALENDAR_DESCRIPTION = (
    "Upcoming events at MetLife Stadium, excluding New York Giants games, "
    "Jets vs. Giants games, and Jets playoff games."
)

ALL_EVENTS_CALENDAR_NAME = "MetLife Stadium All Events"
ALL_EVENTS_CALENDAR_DESCRIPTION = (
    "All legitimate public events at MetLife Stadium."
)

TIMEZONE_NAME = "America/New_York"
LOCAL_TIMEZONE = ZoneInfo(TIMEZONE_NAME)

DEFAULT_EVENT_DURATION_HOURS = 4
RETENTION_DAYS = 7

# Keep DTSTAMP deterministic so the calendars do not change merely
# because the GitHub Action ran again.
DTSTAMP = "20260905T120000Z"


# These events disappeared from Ticketmaster before the retention system
# was corrected. They automatically age out of both feeds after seven days.
BOOTSTRAP_RECENT_EVENTS = [
    {
        "id": "bootstrap-ed-sheeran-20260904",
        "name": "Ed Sheeran: LOOP Tour",
        "url": (
            "https://www.ticketmaster.com/"
            "ed-sheeran-loop-tour-east-rutherford-new-jersey-"
            "09-04-2026/event/00006331CC3A2A14"
        ),
        "start": {
            "localDate": "2026-09-04",
            "dateTime": "2026-09-04T21:30:00Z",
            "timeTBA": False,
            "dateTBA": False,
            "dateTBD": False,
            "noSpecificTime": False,
        },
        "status": "onsale",
        "venue": {
            "name": "MetLife Stadium",
        },
        "classifications": [
            {
                "segment": "Music",
                "genre": "Pop",
                "subGenre": None,
            }
        ],
    },
    {
        "id": "k7vGFbS6CwwcM",
        "name": "Ed Sheeran: LOOP Tour",
        "url": (
            "https://www.ticketmaster.com/"
            "ed-sheeran-loop-tour-east-rutherford-new-jersey-"
            "09-05-2026/event/00006331CECB2B77"
        ),
        "start": {
            "localDate": "2026-09-05",
            "dateTime": "2026-09-05T21:30:00Z",
            "timeTBA": False,
            "dateTBA": False,
            "dateTBD": False,
            "noSpecificTime": False,
        },
        "status": "onsale",
        "venue": {
            "name": "MetLife Stadium",
        },
        "classifications": [
            {
                "segment": "Music",
                "genre": "Pop",
                "subGenre": None,
            }
        ],
    },
]


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


def is_jets_giants_game(name):
    lower_name = " ".join(name.casefold().split())

    return (
        "new york jets" in lower_name
        and "new york giants" in lower_name
    )


def is_jets_playoff_game(name):
    lower_name = " ".join(name.casefold().split())

    if "new york jets" not in lower_name:
        return False

    playoff_terms = (
        "playoff",
        "wild card",
        "wildcard",
        "divisional",
        "afc championship",
    )

    return any(
        term in lower_name
        for term in playoff_terms
    )


def include_in_standard_calendar(event):
    name = event.get("name", "")
    lower_name = " ".join(name.casefold().split())

    # Giants home games are already covered by the user's
    # official New York Giants calendar.
    if lower_name.startswith("new york giants"):
        return False

    # Jets vs. Giants is also already covered by the Giants calendar,
    # regardless of which team is designated as the home team.
    if is_jets_giants_game(name):
        return False

    # Jets postseason home games are already covered by the user's
    # separate NFL Playoffs calendar.
    if is_jets_playoff_game(name):
        return False

    return True


def event_uid(event, all_events=False):
    event_id = event["id"]

    if all_events:
        return f"metlife-all-{event_id}@github-calendar"

    # Preserve the exact UID scheme already used by the existing feed.
    return f"metlife-{event_id}@github-calendar"


def event_local_date(event):
    start = event.get("start", {})

    local_date = start.get("localDate")

    if local_date:
        try:
            return datetime.strptime(
                local_date,
                "%Y-%m-%d",
            ).date()
        except ValueError:
            pass

    utc_datetime = start.get("dateTime")

    if utc_datetime:
        parsed = parse_utc_datetime(utc_datetime)

        if parsed:
            return parsed.astimezone(
                LOCAL_TIMEZONE
            ).date()

    return None


def event_sort_datetime(event):
    start = event.get("start", {})

    utc_datetime = start.get("dateTime")

    if utc_datetime:
        parsed = parse_utc_datetime(utc_datetime)

        if parsed:
            return parsed

    local_date = event_local_date(event)

    if local_date:
        local_midnight = datetime(
            local_date.year,
            local_date.month,
            local_date.day,
            tzinfo=LOCAL_TIMEZONE,
        )

        return local_midnight.astimezone(
            timezone.utc
        )

    return datetime.max.replace(
        tzinfo=timezone.utc
    )


def build_event_lines(event, all_events=False):
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
        f"UID:{escape_ics_text(event_uid(event, all_events))}",
        f"DTSTAMP:{DTSTAMP}",
        f"SUMMARY:{escape_ics_text(name)}",
        f"LOCATION:{escape_ics_text(build_location(event))}",
        f"DESCRIPTION:{escape_ics_text(build_description(event))}",
    ]

    event_url = event.get("url")

    if event_url:
        lines.append(
            f"URL:{escape_ics_text(event_url)}"
        )

    has_specific_time = (
        utc_datetime
        and not time_tba
        and not no_specific_time
        and not date_tba
        and not date_tbd
    )

    if has_specific_time:
        start_datetime = parse_utc_datetime(
            utc_datetime
        )

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

        end_date = start_date + timedelta(
            days=1
        )

        lines.append(
            f"DTSTART;VALUE=DATE:"
            f"{format_date(start_date.isoformat())}"
        )
        lines.append(
            f"DTEND;VALUE=DATE:"
            f"{format_date(end_date.isoformat())}"
        )

    else:
        return None

    lines.append("END:VEVENT")

    return lines


def unfold_ics_lines(text):
    physical_lines = (
        text
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .split("\n")
    )

    unfolded = []

    for line in physical_lines:
        if not line:
            continue

        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)

    return unfolded


def read_existing_event_blocks(output_file):
    if not output_file.exists():
        return []

    text = output_file.read_text(
        encoding="utf-8"
    )

    lines = unfold_ics_lines(text)

    blocks = []
    current = None

    for line in lines:
        if line == "BEGIN:VEVENT":
            current = [line]
            continue

        if current is not None:
            current.append(line)

            if line == "END:VEVENT":
                blocks.append(current)
                current = None

    return blocks


def get_property_line(block, property_name):
    for line in block:
        if (
            line.startswith(property_name + ":")
            or line.startswith(property_name + ";")
        ):
            return line

    return None


def get_property_value(block, property_name):
    line = get_property_line(
        block,
        property_name,
    )

    if not line or ":" not in line:
        return None

    return line.split(":", 1)[1]


def existing_event_start(block):
    line = get_property_line(
        block,
        "DTSTART",
    )

    if not line or ":" not in line:
        return None

    prefix, value = line.split(":", 1)

    if "VALUE=DATE" in prefix:
        try:
            event_date = datetime.strptime(
                value,
                "%Y%m%d",
            ).date()
        except ValueError:
            return None

        local_datetime = datetime(
            event_date.year,
            event_date.month,
            event_date.day,
            tzinfo=LOCAL_TIMEZONE,
        )

        return {
            "datetime": local_datetime,
            "local_date": event_date,
            "all_day": True,
        }

    try:
        if value.endswith("Z"):
            parsed = datetime.strptime(
                value,
                "%Y%m%dT%H%M%SZ",
            ).replace(
                tzinfo=timezone.utc
            )
        else:
            parsed = datetime.strptime(
                value,
                "%Y%m%dT%H%M%S",
            ).replace(
                tzinfo=LOCAL_TIMEZONE
            )
    except ValueError:
        return None

    local_datetime = parsed.astimezone(
        LOCAL_TIMEZONE
    )

    return {
        "datetime": local_datetime,
        "local_date": local_datetime.date(),
        "all_day": False,
    }


def should_retain_existing_event(
    block,
    now_local,
    cutoff_date,
):
    start = existing_event_start(block)

    if not start:
        return False

    local_date = start["local_date"]

    if local_date < cutoff_date:
        return False

    if local_date > now_local.date():
        return False

    if start["all_day"]:
        return True

    return start["datetime"] <= now_local


def existing_event_sort_datetime(block):
    start = existing_event_start(block)

    if not start:
        return datetime.max.replace(
            tzinfo=timezone.utc
        )

    return start["datetime"].astimezone(
        timezone.utc
    )


def bootstrap_events_for_today(
    now_local,
    cutoff_date,
):
    active = []

    for event in BOOTSTRAP_RECENT_EVENTS:
        local_date = event_local_date(event)

        if not local_date:
            continue

        if (
            cutoff_date
            <= local_date
            <= now_local.date()
        ):
            active.append(event)

    return active


def generate_feed(
    events,
    output_file,
    calendar_name,
    calendar_description,
    all_events,
):
    # Read the existing file before overwriting it so recently completed
    # events can survive Ticketmaster removing them from its API results.
    existing_blocks = read_existing_event_blocks(
        output_file
    )

    now_local = datetime.now(
        LOCAL_TIMEZONE
    )

    cutoff_date = (
        now_local.date()
        - timedelta(days=RETENTION_DAYS)
    )

    calendar_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Matt Malinconico//MetLife Stadium Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape_ics_text(calendar_name)}",
        f"X-WR-TIMEZONE:{TIMEZONE_NAME}",
        (
            "X-WR-CALDESC:"
            f"{escape_ics_text(calendar_description)}"
        ),
        "REFRESH-INTERVAL;VALUE=DURATION:P1D",
        "X-PUBLISHED-TTL:P1D",
    ]

    calendar_items = []
    active_uids = set()

    current_count = 0
    retained_count = 0
    bootstrap_count = 0
    filtered_count = 0
    skipped_count = 0

    for event in events:
        if should_skip_event(event):
            skipped_count += 1
            continue

        if (
            not all_events
            and not include_in_standard_calendar(event)
        ):
            filtered_count += 1
            continue

        event_lines = build_event_lines(
            event,
            all_events=all_events,
        )

        if not event_lines:
            print(
                f"Skipping event with no usable date: "
                f"{event.get('name')}"
            )
            skipped_count += 1
            continue

        uid = event_uid(
            event,
            all_events=all_events,
        )

        active_uids.add(uid)

        calendar_items.append(
            (
                event_sort_datetime(event),
                event_lines,
            )
        )

        current_count += 1

    # Recover the two recent Ed Sheeran events until they naturally
    # age out of the seven-day retention window.
    for event in bootstrap_events_for_today(
        now_local,
        cutoff_date,
    ):
        if (
            not all_events
            and not include_in_standard_calendar(event)
        ):
            continue

        uid = event_uid(
            event,
            all_events=all_events,
        )

        if uid in active_uids:
            continue

        event_lines = build_event_lines(
            event,
            all_events=all_events,
        )

        if not event_lines:
            continue

        active_uids.add(uid)

        calendar_items.append(
            (
                event_sort_datetime(event),
                event_lines,
            )
        )

        bootstrap_count += 1

    # Carry forward recently completed events from this feed's previous
    # published file when Ticketmaster has stopped returning them.
    for block in existing_blocks:
        uid = get_property_value(
            block,
            "UID",
        )

        if not uid:
            continue

        if uid in active_uids:
            continue

        if not should_retain_existing_event(
            block,
            now_local,
            cutoff_date,
        ):
            continue

        active_uids.add(uid)

        calendar_items.append(
            (
                existing_event_sort_datetime(block),
                block,
            )
        )

        retained_count += 1

    calendar_items.sort(
        key=lambda item: item[0]
    )

    for _, event_lines in calendar_items:
        calendar_lines.extend(
            event_lines
        )

    calendar_lines.append(
        "END:VCALENDAR"
    )

    folded_lines = [
        fold_ics_line(line)
        for line in calendar_lines
    ]

    calendar_text = (
        "\r\n".join(folded_lines)
        + "\r\n"
    )

    output_file.write_text(
        calendar_text,
        encoding="utf-8",
        newline="",
    )

    print()
    print(f"Calendar: {calendar_name}")
    print(f"File: {output_file}")
    print(
        f"Current/upcoming events written: "
        f"{current_count}"
    )
    print(
        f"Recent completed events retained: "
        f"{retained_count}"
    )
    print(
        f"Bootstrap recent events restored: "
        f"{bootstrap_count}"
    )
    print(
        f"Events excluded by feed rules: "
        f"{filtered_count}"
    )
    print(
        f"Events skipped: "
        f"{skipped_count}"
    )
    print(
        f"Retention window: "
        f"{RETENTION_DAYS} days"
    )


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

        events = payload.get(
            "events",
            [],
        )

        generate_feed(
            events=events,
            output_file=STANDARD_OUTPUT_FILE,
            calendar_name=STANDARD_CALENDAR_NAME,
            calendar_description=STANDARD_CALENDAR_DESCRIPTION,
            all_events=False,
        )

        generate_feed(
            events=events,
            output_file=ALL_EVENTS_OUTPUT_FILE,
            calendar_name=ALL_EVENTS_CALENDAR_NAME,
            calendar_description=ALL_EVENTS_CALENDAR_DESCRIPTION,
            all_events=True,
        )

        print()
        print("Both calendar feeds generated successfully.")

    except Exception as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
