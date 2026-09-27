import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


INPUT_FILE = Path("events.json")

STANDARD_OUTPUT_FILE = Path("metlife-stadium-calendar.ics")
ALL_EVENTS_OUTPUT_FILE = Path("metlife-stadium-all-events.ics")

STANDARD_CALENDAR_NAME = "MetLife Stadium Events"
STANDARD_CALENDAR_DESCRIPTION = (
    "Upcoming events at MetLife Stadium, excluding New York Giants games "
    "and NFL postseason games covered by the user's other calendars."
)

ALL_EVENTS_CALENDAR_NAME = "MetLife Stadium All Events"
ALL_EVENTS_CALENDAR_DESCRIPTION = (
    "All legitimate public events at MetLife Stadium."
)

TIMEZONE_NAME = "America/New_York"
LOCAL_TIMEZONE = ZoneInfo(TIMEZONE_NAME)

SPORTS_EVENT_DURATION_HOURS = 3
DEFAULT_EVENT_DURATION_HOURS = 4
CONCERT_END_HOUR = 23
RETENTION_DAYS = 7

NFL_PLAYOFF_CALENDAR_URL = (
    "https://mmalinconico.github.io/"
    "nfl-playoff-calendar/nfl-playoffs.ics"
)
NFL_PLAYOFF_FETCH_TIMEOUT_SECONDS = 20
NFL_PLAYOFF_FETCH_ATTEMPTS = 3
NFL_PLAYOFF_RETRY_DELAYS_SECONDS = (5, 15)

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


NFL_TEAM_ALIASES = {
    "Arizona Cardinals": ("arizona cardinals", "cardinals"),
    "Atlanta Falcons": ("atlanta falcons", "falcons"),
    "Baltimore Ravens": ("baltimore ravens", "ravens"),
    "Buffalo Bills": ("buffalo bills", "bills"),
    "Carolina Panthers": ("carolina panthers", "panthers"),
    "Chicago Bears": ("chicago bears", "bears"),
    "Cincinnati Bengals": ("cincinnati bengals", "bengals"),
    "Cleveland Browns": ("cleveland browns", "browns"),
    "Dallas Cowboys": ("dallas cowboys", "cowboys"),
    "Denver Broncos": ("denver broncos", "broncos"),
    "Detroit Lions": ("detroit lions", "lions"),
    "Green Bay Packers": ("green bay packers", "packers"),
    "Houston Texans": ("houston texans", "texans"),
    "Indianapolis Colts": ("indianapolis colts", "colts"),
    "Jacksonville Jaguars": ("jacksonville jaguars", "jaguars"),
    "Kansas City Chiefs": ("kansas city chiefs", "chiefs"),
    "Las Vegas Raiders": ("las vegas raiders", "raiders"),
    "Los Angeles Chargers": ("los angeles chargers", "chargers"),
    "Los Angeles Rams": ("los angeles rams", "rams"),
    "Miami Dolphins": ("miami dolphins", "dolphins"),
    "Minnesota Vikings": ("minnesota vikings", "vikings"),
    "New England Patriots": ("new england patriots", "patriots"),
    "New Orleans Saints": ("new orleans saints", "saints"),
    "New York Giants": ("new york giants", "ny giants", "nyg", "giants"),
    "New York Jets": ("new york jets", "ny jets", "nyj", "jets"),
    "Philadelphia Eagles": ("philadelphia eagles", "eagles"),
    "Pittsburgh Steelers": ("pittsburgh steelers", "steelers"),
    "San Francisco 49ers": ("san francisco 49ers", "49ers"),
    "Seattle Seahawks": ("seattle seahawks", "seahawks"),
    "Tampa Bay Buccaneers": ("tampa bay buccaneers", "buccaneers", "bucs"),
    "Tennessee Titans": ("tennessee titans", "titans"),
    "Washington Commanders": ("washington commanders", "commanders"),
}

POSTSEASON_TERMS = (
    "postseason",
    "playoff",
    "wild card",
    "wildcard",
    "divisional",
    "conference championship",
    "afc championship",
    "nfc championship",
    "super bowl",
)

NFL_NON_GAME_TERMS = (
    "opening night",
    "experience",
    "fan fest",
    "fan festival",
    "tailgate",
    "watch party",
    "draft",
    "training camp",
    "practice",
    "tour",
    "season tickets",
    "parking",
    "hospitality",
    "suite",
)

MATCHUP_MARKERS = (
    " vs ",
    " vs. ",
    " v ",
    " v. ",
    " @ ",
    " at ",
)


def normalized_name(value):
    return " ".join((value or "").casefold().split())


def contains_phrase(text, phrase):
    return bool(
        re.search(
            r"(?<![a-z0-9])"
            + re.escape(phrase)
            + r"(?![a-z0-9])",
            text,
        )
    )


def classification_values(classifications):
    values = []

    for classification in classifications:
        for key in ("segment", "genre", "subGenre"):
            value = classification.get(key)

            if value:
                values.append(
                    normalized_name(value)
                )

    return values


def event_classification_values(event):
    values = classification_values(
        event.get("classifications", [])
    )

    # Ticketmaster also attaches classifications to the participating
    # attractions. Preserve those as a second signal in case the event-level
    # classification is incomplete or malformed.
    for attraction in event.get("attractions", []):
        values.extend(
            classification_values(
                attraction.get("classifications", [])
            )
        )

    return values


def is_football_classified(event):
    values = event_classification_values(event)

    return (
        "nfl" in values
        or "football" in values
    )


def nfl_teams_in_text(value):
    lower_value = normalized_name(value)
    teams = set()

    for team, aliases in NFL_TEAM_ALIASES.items():
        for alias in aliases:
            if contains_phrase(
                lower_value,
                alias,
            ):
                teams.add(team)
                break

    return teams


def extract_nfl_teams(event):
    teams = nfl_teams_in_text(
        event.get("name", "")
    )

    # Ticketmaster normally includes the participating teams as attractions.
    # Using those names makes ownership resilient to abbreviated or unusual
    # event titles such as a relocated matchup.
    for attraction in event.get("attractions", []):
        teams.update(
            nfl_teams_in_text(
                attraction.get("name", "")
            )
        )

    return teams


def is_known_nfl_non_game(name):
    lower_name = normalized_name(name)

    return any(
        term in lower_name
        for term in NFL_NON_GAME_TERMS
    )


def is_named_super_bowl_game(name):
    lower_name = normalized_name(name)

    # Recognize the actual Super Bowl even if Ticketmaster's NFL/football
    # classification is missing or malformed. Requiring a Roman numeral
    # or number avoids treating generic Super Bowl-branded side events
    # as the game itself. Known non-game terms are checked first by
    # is_nfl_game().
    return bool(
        re.search(
            r"(?<![a-z0-9])super bowl "
            r"(?:[ivxlcdm]+|[0-9]+)"
            r"(?![a-z0-9])",
            lower_name,
        )
    )


def is_nfl_game(event):
    name = event.get("name", "")
    lower_name = normalized_name(name)

    if not lower_name:
        return False

    if is_known_nfl_non_game(name):
        return False

    if is_named_super_bowl_game(name):
        return True

    teams = extract_nfl_teams(event)
    football_classified = is_football_classified(
        event
    )

    # A matchup between two known NFL teams is a game even if
    # Ticketmaster's classification is incomplete.
    if len(teams) >= 2:
        return True

    # Ticketmaster can publish placeholders such as a team vs. TBD.
    # Require football/NFL classification before treating a one-team
    # matchup-style title as a game.
    if football_classified and teams:
        if any(
            marker in f" {lower_name} "
            for marker in MATCHUP_MARKERS
        ):
            return True

        explicit_game_terms = (
            "preseason game",
            "regular season game",
            "home game",
            "away game",
        )

        if any(
            term in lower_name
            for term in explicit_game_terms
        ):
            return True

    # Named postseason rounds can be valid game listings before teams
    # are known. Non-game Super Bowl/NFL events were filtered above.
    if (
        football_classified
        and any(
            term in lower_name
            for term in POSTSEASON_TERMS
        )
    ):
        return True

    return False


def is_giants_game(event):
    if not is_nfl_game(event):
        return False

    return (
        "New York Giants"
        in extract_nfl_teams(event)
    )


def is_explicit_nfl_postseason_game(event):
    if not is_nfl_game(event):
        return False

    lower_name = normalized_name(
        event.get("name", "")
    )

    return any(
        term in lower_name
        for term in POSTSEASON_TERMS
    )


def is_nfl_postseason_game(
    event,
    nfl_playoff_dates,
):
    if not is_nfl_game(event):
        return False

    # First use explicit Ticketmaster wording when it is available.
    if is_explicit_nfl_postseason_game(event):
        return True

    # The separate NFL Playoffs calendar is the authoritative ownership
    # reference. If an NFL game at MetLife falls on a date represented
    # in that feed, the Playoffs calendar owns it even when Ticketmaster
    # names the event only by the two teams.
    local_date = event_local_date(event)

    return (
        local_date is not None
        and local_date in nfl_playoff_dates
    )


def include_in_standard_calendar(
    event,
    nfl_playoff_dates,
):
    # Every actual Giants game belongs to the official Giants calendar,
    # regardless of venue, opponent, or home/away designation.
    if is_giants_game(event):
        return False

    # Every other NFL postseason game belongs to the separate NFL
    # Playoffs calendar. Preseason and regular-season games remain in
    # the MetLife feed, regardless of which team is designated home.
    if is_nfl_postseason_game(
        event,
        nfl_playoff_dates,
    ):
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


def event_segment(event):
    classifications = event.get(
        "classifications",
        [],
    )

    for classification in classifications:
        segment = classification.get("segment")

        if segment:
            return segment.casefold()

    return ""


def calculate_event_end(event, start_datetime):
    segment = event_segment(event)

    if segment == "sports":
        return start_datetime + timedelta(
            hours=SPORTS_EVENT_DURATION_HOURS
        )

    if segment == "music":
        local_start = start_datetime.astimezone(
            LOCAL_TIMEZONE
        )

        local_end = datetime(
            local_start.year,
            local_start.month,
            local_start.day,
            CONCERT_END_HOUR,
            0,
            0,
            tzinfo=LOCAL_TIMEZONE,
        )

        concert_end = local_end.astimezone(
            timezone.utc
        )

        # If an unusual event begins at or after 11 PM,
        # avoid creating an end time before or equal to
        # the event's start time.
        if concert_end > start_datetime:
            return concert_end

    return start_datetime + timedelta(
        hours=DEFAULT_EVENT_DURATION_HOURS
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
            end_datetime = calculate_event_end(
                event,
                start_datetime,
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


def calendar_date_from_dtstart_line(line):
    if not line or ":" not in line:
        return None

    prefix, value = line.split(":", 1)
    value = value.strip()

    if "VALUE=DATE" in prefix:
        try:
            return datetime.strptime(
                value,
                "%Y%m%d",
            ).date()
        except ValueError:
            return None

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

    return parsed.astimezone(
        LOCAL_TIMEZONE
    ).date()


def parse_calendar_event_dates(calendar_text):
    dates = set()
    current_dtstart = None
    inside_event = False

    for line in unfold_ics_lines(calendar_text):
        if line == "BEGIN:VEVENT":
            inside_event = True
            current_dtstart = None
            continue

        if line == "END:VEVENT":
            if inside_event and current_dtstart:
                event_date = (
                    calendar_date_from_dtstart_line(
                        current_dtstart
                    )
                )

                if event_date:
                    dates.add(event_date)

            inside_event = False
            current_dtstart = None
            continue

        if (
            inside_event
            and (
                line.startswith("DTSTART:")
                or line.startswith("DTSTART;")
            )
        ):
            current_dtstart = line

    return dates


def fetch_nfl_playoff_dates():
    last_error = None

    for attempt in range(
        1,
        NFL_PLAYOFF_FETCH_ATTEMPTS + 1,
    ):
        try:
            request = urllib.request.Request(
                NFL_PLAYOFF_CALENDAR_URL,
                headers={
                    "User-Agent": (
                        "MetLife-Stadium-Calendar/1.0"
                    ),
                },
            )

            with urllib.request.urlopen(
                request,
                timeout=(
                    NFL_PLAYOFF_FETCH_TIMEOUT_SECONDS
                ),
            ) as response:
                calendar_text = (
                    response
                    .read()
                    .decode("utf-8-sig")
                )

            dates = parse_calendar_event_dates(
                calendar_text
            )

            if not dates:
                raise RuntimeError(
                    "NFL Playoffs calendar contained "
                    "no event dates."
                )

            print(
                "NFL Playoffs ownership dates loaded: "
                f"{len(dates)}"
            )

            return dates

        except (
            urllib.error.URLError,
            TimeoutError,
            RuntimeError,
            UnicodeDecodeError,
        ) as error:
            last_error = error

            if (
                attempt
                >= NFL_PLAYOFF_FETCH_ATTEMPTS
            ):
                break

            delay = (
                NFL_PLAYOFF_RETRY_DELAYS_SECONDS[
                    attempt - 1
                ]
            )

            print(
                "Could not load NFL Playoffs calendar: "
                f"{error}. Retrying in {delay} seconds "
                f"(attempt {attempt + 1} of "
                f"{NFL_PLAYOFF_FETCH_ATTEMPTS})..."
            )

            time.sleep(delay)

    # Fail closed. The NFL Playoffs feed is an ownership dependency for
    # the standard MetLife feed. Publishing without it could duplicate a
    # postseason game whose Ticketmaster title contains only the matchup.
    raise RuntimeError(
        "NFL Playoffs calendar could not be loaded after "
        f"{NFL_PLAYOFF_FETCH_ATTEMPTS} attempts. "
        "Refusing to generate new MetLife calendar files so "
        "the last known-good published feeds remain in place. "
        f"Last error: {last_error}"
    )


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
    nfl_playoff_dates,
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
            and not include_in_standard_calendar(
                event,
                nfl_playoff_dates,
            )
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
            and not include_in_standard_calendar(
                event,
                nfl_playoff_dates,
            )
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

        nfl_playoff_dates = (
            fetch_nfl_playoff_dates()
        )

        generate_feed(
            events=events,
            output_file=STANDARD_OUTPUT_FILE,
            calendar_name=STANDARD_CALENDAR_NAME,
            calendar_description=STANDARD_CALENDAR_DESCRIPTION,
            all_events=False,
            nfl_playoff_dates=nfl_playoff_dates,
        )

        generate_feed(
            events=events,
            output_file=ALL_EVENTS_OUTPUT_FILE,
            calendar_name=ALL_EVENTS_CALENDAR_NAME,
            calendar_description=ALL_EVENTS_CALENDAR_DESCRIPTION,
            all_events=True,
            nfl_playoff_dates=nfl_playoff_dates,
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