import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests


API_BASE = "https://app.ticketmaster.com/discovery/v2"
VENUE_NAME = "MetLife Stadium"
VENUE_CITY = "East Rutherford"
VENUE_STATE = "NJ"
TIMEZONE_NAME = "America/New_York"
OUTPUT_FILE = "events.json"

REQUEST_TIMEOUT = 30
PAGE_SIZE = 200


def get_api_key():
    api_key = os.environ.get("TICKETMASTER_API_KEY")

    if not api_key:
        raise RuntimeError(
            "TICKETMASTER_API_KEY environment variable is not set."
        )

    return api_key


def api_get(session, api_key, path, params=None):
    if params is None:
        params = {}

    params = dict(params)
    params["apikey"] = api_key

    url = f"{API_BASE}/{path}"

    response = session.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()
    return response.json()


def find_metlife_venue(session, api_key):
    data = api_get(
        session,
        api_key,
        "venues.json",
        {
            "keyword": VENUE_NAME,
            "size": 50,
        },
    )

    venues = data.get("_embedded", {}).get("venues", [])

    # First choice: exact venue name, city and state.
    for venue in venues:
        name = venue.get("name", "")
        city = venue.get("city", {}).get("name", "")
        state = venue.get("state", {}).get("stateCode", "")

        if (
            name.casefold() == VENUE_NAME.casefold()
            and city.casefold() == VENUE_CITY.casefold()
            and state.casefold() == VENUE_STATE.casefold()
        ):
            return venue

    # Fallback: exact venue name and state.
    for venue in venues:
        name = venue.get("name", "")
        state = venue.get("state", {}).get("stateCode", "")

        if (
            name.casefold() == VENUE_NAME.casefold()
            and state.casefold() == VENUE_STATE.casefold()
        ):
            return venue

    candidates = []

    for venue in venues:
        candidates.append(
            {
                "name": venue.get("name"),
                "city": venue.get("city", {}).get("name"),
                "state": venue.get("state", {}).get("stateCode"),
                "id": venue.get("id"),
            }
        )

    raise RuntimeError(
        "Could not identify MetLife Stadium in Ticketmaster venue results.\n"
        f"Candidates returned: {json.dumps(candidates, indent=2)}"
    )


def get_start_datetime():
    eastern = ZoneInfo(TIMEZONE_NAME)

    now_eastern = datetime.now(eastern)

    start_of_today = now_eastern.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    return start_of_today.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def fetch_events(session, api_key, venue_id):
    all_events = []
    page_number = 0

    while True:
        data = api_get(
            session,
            api_key,
            "events.json",
            {
                "venueId": venue_id,
                "startDateTime": get_start_datetime(),
                "size": PAGE_SIZE,
                "page": page_number,
                "sort": "startDate,asc",
            },
        )

        events = data.get("_embedded", {}).get("events", [])
        all_events.extend(events)

        page_info = data.get("page", {})
        total_pages = page_info.get("totalPages", 1)

        if page_number + 1 >= total_pages:
            break

        page_number += 1

    # Protect against duplicate API records.
    deduplicated = {}

    for event in all_events:
        event_id = event.get("id")

        if event_id:
            deduplicated[event_id] = event

    return list(deduplicated.values())


def is_jets_giants_game(lower_name):
    return (
        "new york jets" in lower_name
        and "new york giants" in lower_name
    )


def is_jets_playoff_game(lower_name):
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


def exclusion_reason(event):
    if event.get("test"):
        return "Ticketmaster test event"

    name = event.get("name", "").strip()
    lower_name = " ".join(name.casefold().split())

    # Exclude every Giants home game.
    if lower_name.startswith("new york giants"):
        return "New York Giants home game"

    # Also exclude Jets/Giants games even when the Jets are designated
    # as the home team. The user's official Giants calendar already
    # covers this matchup.
    if is_jets_giants_game(lower_name):
        return "Jets vs. Giants game already covered by Giants calendar"

    # Exclude Jets postseason home games because those are already
    # covered by the separate NFL Playoffs calendar.
    if is_jets_playoff_game(lower_name):
        return "Jets playoff game already covered by NFL Playoffs calendar"

    # Ticketmaster sometimes lists ancillary products as separate events.
    # These are not actual stadium events and would create duplicates/noise.
    junk_terms = (
        "parking",
        "official platinum",
        "vip package",
        "suite rental",
        "suite package",
        "premium seating",
        "club seating",
        "club access",
        "hospitality package",
    )

    for term in junk_terms:
        if term in lower_name:
            return f"Ancillary listing: {term}"

    if lower_name.startswith("metlife stadium tour"):
        return "Stadium tour"

    if lower_name.startswith("metlife stadium vip tour"):
        return "Stadium tour"

    return None


def normalize_classifications(event):
    normalized = []

    for classification in event.get("classifications", []):
        normalized.append(
            {
                "segment": classification.get("segment", {}).get("name"),
                "genre": classification.get("genre", {}).get("name"),
                "subGenre": classification.get("subGenre", {}).get("name"),
            }
        )

    return normalized


def normalize_event(event):
    venues = event.get("_embedded", {}).get("venues", [])
    venue = venues[0] if venues else {}

    return {
        "id": event.get("id"),
        "name": event.get("name"),
        "url": event.get("url"),
        "start": event.get("dates", {}).get("start", {}),
        "status": event.get("dates", {}).get("status", {}).get("code"),
        "venue": {
            "name": venue.get("name", VENUE_NAME),
            "timeZone": venue.get("timezone", TIMEZONE_NAME),
            "address": venue.get("address", {}).get("line1"),
            "city": venue.get("city", {}).get("name"),
            "state": venue.get("state", {}).get("stateCode"),
            "postalCode": venue.get("postalCode"),
        },
        "classifications": normalize_classifications(event),
        "info": event.get("info"),
        "pleaseNote": event.get("pleaseNote"),
    }


def main():
    try:
        api_key = get_api_key()

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": (
                    "metlife-stadium-calendar/1.0 "
                    "(GitHub Actions calendar generator)"
                )
            }
        )

        venue = find_metlife_venue(session, api_key)

        venue_id = venue.get("id")

        if not venue_id:
            raise RuntimeError("MetLife Stadium venue ID was missing.")

        print(
            f"Using venue: {venue.get('name')} "
            f"({venue.get('city', {}).get('name')}, "
            f"{venue.get('state', {}).get('stateCode')})"
        )
        print(f"Ticketmaster venue ID: {venue_id}")

        raw_events = fetch_events(session, api_key, venue_id)

        included_events = []
        excluded_events = []

        for event in raw_events:
            reason = exclusion_reason(event)

            if reason:
                excluded_events.append(
                    {
                        "id": event.get("id"),
                        "name": event.get("name"),
                        "reason": reason,
                    }
                )
                continue

            included_events.append(normalize_event(event))

        payload = {
            "generatedAt": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "source": "Ticketmaster Discovery API",
            "venueId": venue_id,
            "venue": {
                "name": venue.get("name"),
                "city": venue.get("city", {}).get("name"),
                "state": venue.get("state", {}).get("stateCode"),
            },
            "eventCount": len(included_events),
            "excludedCount": len(excluded_events),
            "excludedEvents": excluded_events,
            "events": included_events,
        }

        with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
            json.dump(
                payload,
                file,
                indent=2,
                ensure_ascii=False,
            )
            file.write("\n")

        print()
        print(f"Ticketmaster events returned: {len(raw_events)}")
        print(f"Events included: {len(included_events)}")
        print(f"Events excluded: {len(excluded_events)}")
        print(f"Wrote {OUTPUT_FILE}")

        if excluded_events:
            print()
            print("Excluded listings:")

            for event in excluded_events:
                print(
                    f"- {event['name']} "
                    f"({event['reason']})"
                )

    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
