"""Validate both published ICS feeds for structural and iOS compatibility."""
import argparse
import re
from datetime import datetime
from pathlib import Path

import generate_calendar as calendar

FEEDS = ("metlife-stadium-calendar.ics", "metlife-stadium-all-events.ics")


def validate_feed(path):
    raw = Path(path).read_bytes()
    if not raw or not raw.endswith(b"\r\n") or b"\n" in raw.replace(b"\r\n", b""):
        raise ValueError(f"{path}: invalid or inconsistent CRLF line endings")
    if any(len(line) > 75 for line in raw.split(b"\r\n")):
        raise ValueError(f"{path}: a folded physical line exceeds 75 octets")
    lines = calendar.unfold_ics_lines(raw.decode("utf-8-sig"))
    if not lines or lines[0] != "BEGIN:VCALENDAR" or lines[-1] != "END:VCALENDAR":
        raise ValueError(f"{path}: missing VCALENDAR boundaries")
    if lines.count("BEGIN:VCALENDAR") != 1 or lines.count("END:VCALENDAR") != 1:
        raise ValueError(f"{path}: duplicate VCALENDAR boundaries")
    if "VERSION:2.0" not in lines or not any(x.startswith("PRODID:") for x in lines):
        raise ValueError(f"{path}: missing VERSION/PRODID")

    uids = set()
    current = None
    for line in lines[1:-1]:
        if line == "BEGIN:VEVENT":
            if current is not None:
                raise ValueError(f"{path}: nested VEVENT")
            current = []
        elif line == "END:VEVENT":
            if current is None:
                raise ValueError(f"{path}: unexpected VEVENT closing")
            props = {}
            for item in current:
                if ":" not in item:
                    raise ValueError(f"{path}: malformed property {item!r}")
                key, value = item.split(":", 1)
                props.setdefault(key.split(";", 1)[0], []).append((key, value))
            required = {"UID", "DTSTAMP", "SUMMARY", "DTSTART", "DTEND",
                        "LOCATION", "DESCRIPTION"}
            if not required.issubset(props):
                raise ValueError(f"{path}: VEVENT missing {required - set(props)}")
            if any(len(props[key]) != 1 for key in required):
                raise ValueError(f"{path}: duplicate required VEVENT property")
            uid = props["UID"][0][1]
            if uid in uids:
                raise ValueError(f"{path}: duplicate UID {uid}")
            uids.add(uid)
            if props["LOCATION"][0][1] != "MetLife Stadium":
                raise ValueError(f"{path}: incorrect event location {uid}")
            startkey, start = props["DTSTART"][0]
            endkey, end = props["DTEND"][0]
            if "VALUE=DATE" in startkey or "VALUE=DATE" in endkey:
                if not ("VALUE=DATE" in startkey and "VALUE=DATE" in endkey):
                    raise ValueError(f"{path}: mixed all-day/timed event {uid}")
                parse = lambda value: datetime.strptime(value, "%Y%m%d")
            else:
                if not (re.fullmatch(r"\d{8}T\d{6}Z", start)
                        and re.fullmatch(r"\d{8}T\d{6}Z", end)):
                    raise ValueError(f"{path}: non-UTC timed event {uid}")
                parse = lambda value: datetime.strptime(value, "%Y%m%dT%H%M%SZ")
            if parse(end) <= parse(start):
                raise ValueError(f"{path}: non-positive event duration {uid}")
            if not re.fullmatch(r"\d{8}T\d{6}Z", props["DTSTAMP"][0][1]):
                raise ValueError(f"{path}: invalid DTSTAMP {uid}")
            current = None
        elif current is not None:
            current.append(line)
    if current is not None:
        raise ValueError(f"{path}: unterminated VEVENT")
    if not uids:
        raise ValueError(f"{path}: calendar contains no events")
    return uids


def validate_both(directory):
    directory = Path(directory)
    standard = validate_feed(directory / FEEDS[0])
    all_events = validate_feed(directory / FEEDS[1])
    if any(not uid.startswith("metlife-") or uid.startswith("metlife-all-")
           for uid in standard):
        raise ValueError("Unexpected standard feed UID prefix")
    if any(not uid.startswith("metlife-all-") for uid in all_events):
        raise ValueError("Unexpected All Events feed UID prefix")
    mapped = {uid.replace("metlife-", "metlife-all-", 1) for uid in standard}
    if mapped - all_events:
        raise ValueError("Standard feed contains events missing from All Events")
    return len(standard), len(all_events)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", default=".")
    args = parser.parse_args()
    result = validate_both(args.directory)
    print(f"ICS validation passed: standard={result[0]}, all_events={result[1]}")
