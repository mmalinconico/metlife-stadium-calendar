"""Offline regression coverage for both MetLife subscription feeds."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import fetch_events as fetch
import generate_calendar as cal
import check_source
import validate_ics

NY = ZoneInfo("America/New_York")


def event(name="New York Jets v. Cleveland Browns", ident="1", segment="Sports",
          genre="Football", local=None, hour=13, attractions=None, status="onsale"):
    if local is None:
        local = (datetime.now(NY) + timedelta(days=30)).date()
    begin = datetime(local.year, local.month, local.day, hour, tzinfo=NY)
    return {
        "id": ident, "name": name, "url": f"https://ticketmaster.com/event/{ident}",
        "start": {"localDate": local.isoformat(),
                  "dateTime": begin.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")},
        "status": status, "venue": {"name": "MetLife Stadium"},
        "classifications": [{"segment": segment, "genre": genre, "subGenre": None}],
        "attractions": [{"name": n, "classifications": []} for n in (attractions or [])],
    }


def snapshot(path, events, all_events=False, playoff_days=frozenset()):
    cal.generate_feed(events, Path(path),
        "MetLife Stadium All Events" if all_events else "MetLife Stadium Events",
        "tests", all_events, playoff_days)


class FilterAndOwnership(unittest.TestCase):
    def test_legitimate_public_events(self):
        for name in ("Jets v Browns", "Live Concert", "Army-Navy Game presented by USAA",
                     "World Cup Soccer", "WWE WrestleMania", "Monster Jam"):
            with self.subTest(name=name):
                self.assertIsNone(fetch.exclusion_reason({"name": name}))

    def test_ancillary_listings(self):
        names = ("MetLife Stadium Tour", "MetLife Stadium VIP Tour", "Parking Pass",
                 "Season Tickets", "Individual Suite Ticket", "Suite Rental",
                 "Suite Package", "Hospitality Package", "VIP Package",
                 "Premium Seating", "Club Seating", "Club Access",
                 "Official Platinum")
        for name in names:
            with self.subTest(name=name):
                self.assertIsNotNone(fetch.exclusion_reason({"name": name}))
        self.assertIsNotNone(fetch.exclusion_reason({"name": "Example", "test": True}))

    def test_two_feed_ownership(self):
        playoff = (datetime.now(NY) + timedelta(days=40)).date()
        cases = (
            ("New York Jets v. Cleveland Browns", True),
            ("Bruce Springsteen", True),
            ("Army-Navy Game presented by USAA", True),
            ("World Cup Soccer", True),
            ("WWE WrestleMania", True),
            ("New York Giants vs Philadelphia Eagles", False),
            ("Buffalo Bills vs Miami Dolphins", False),
            ("Super Bowl LXI", False),
        )
        for i, (name, expected) in enumerate(cases):
            e = event(name, str(i), local=playoff - timedelta(days=1) if i == 0 else playoff)
            with self.subTest(name=name):
                self.assertEqual(cal.include_in_standard_calendar(e, {playoff}), expected)
        self.assertTrue(cal.include_in_standard_calendar(
            event("Giants Fan Fest"), {playoff}))

    def test_unusual_designations_and_attractions(self):
        self.assertFalse(cal.include_in_standard_calendar(
            event("NYG vs PHI", attractions=["New York Giants", "Philadelphia Eagles"]), set()))
        self.assertTrue(cal.include_in_standard_calendar(
            event("Buffalo Bills vs New York Jets"), set()))
        date=(datetime.now(NY)+timedelta(days=35)).date()
        self.assertFalse(cal.include_in_standard_calendar(
            event("Buffalo Bills vs Miami Dolphins", local=date), {date}))

    def test_ticketmaster_attraction_normalization(self):
        raw = {"id":"id", "name":"Match", "dates":{"status":{"code":"onsale"}},
            "_embedded":{"venues":[{"name":"MetLife Stadium", "city":{"name":"East Rutherford"},
                "state":{"stateCode":"NJ"}, "timezone":"America/New_York"}],
                "attractions":[{"id":"a", "name":"New York Jets", "classifications":[
                    {"segment":{"name":"Sports"},"genre":{"name":"Football"}}]}]}}
        normalized=fetch.normalize_event(raw)
        self.assertEqual(normalized["venue"]["city"],"East Rutherford")
        self.assertEqual(normalized["attractions"][0]["name"],"New York Jets")
        self.assertEqual(normalized["attractions"][0]["classifications"][0]["genre"],"Football")


class NamingAndTimes(unittest.TestCase):
    def test_away_home_conversion(self):
        e=event(attractions=["New York Jets", "Cleveland Browns"])
        self.assertEqual(cal.calendar_event_name(e), "Cleveland Browns @ New York Jets")
        e["name"]="Cleveland Browns at New York Jets"
        self.assertEqual(cal.calendar_event_name(e), "Cleveland Browns @ New York Jets")
        e["name"]="New York Jets @ Cleveland Browns"
        self.assertEqual(cal.calendar_event_name(e), "New York Jets @ Cleveland Browns")

    def test_neutral_site_promotional_title(self):
        e=event("Army-Navy Game presented by USAA",local=datetime(2026,12,12).date())
        self.assertEqual(cal.calendar_event_name(e),
            "Navy Midshipmen Football @ Army Black Knights Football")
        e["start"]["localDate"]="2027-12-12"
        self.assertEqual(cal.calendar_event_name(e), "Army-Navy Game presented by USAA")

    def test_soccer_conversion_without_wrestling_conversion(self):
        e=event("Club A vs Club B",genre="Soccer",attractions=["Club A","Club B"])
        self.assertEqual(cal.calendar_event_name(e),"Club B @ Club A")
        e=event("Wrestler A vs Wrestler B",genre="Wrestling")
        self.assertEqual(cal.calendar_event_name(e),e["name"])

    def test_duration_and_daylight_saving(self):
        for local, offset in ((datetime(2026,10,25).date(),"-0400"),
                              (datetime(2026,11,8).date(),"-0500")):
            e=event(local=local)
            start=cal.parse_utc_datetime(e["start"]["dateTime"])
            self.assertEqual(start.astimezone(NY).strftime("%z"), offset)
            self.assertEqual(cal.calculate_event_end(e,start)-start,timedelta(hours=3))
            concert=event("AC/DC",segment="Music",genre="Rock",local=local,hour=19)
            cstart=cal.parse_utc_datetime(concert["start"]["dateTime"])
            self.assertEqual(cal.calculate_event_end(concert,cstart).astimezone(NY).hour,23)
            other=event("Exhibit",segment="Miscellaneous",genre="Other",local=local)
            ostart=cal.parse_utc_datetime(other["start"]["dateTime"])
            self.assertEqual(cal.calculate_event_end(other,ostart)-ostart,timedelta(hours=4))

    def test_tba_all_day_location(self):
        e=event()
        e["start"]["timeTBA"]=True
        lines=cal.build_event_lines(e)
        self.assertTrue(any(s.startswith("DTSTART;VALUE=DATE:") for s in lines))
        self.assertIn("LOCATION:MetLife Stadium",lines)
        e["start"]["timeTBA"]=False
        e["start"]["noSpecificTime"]=True
        self.assertTrue(any(s.startswith("DTSTART;VALUE=DATE:") for s in cal.build_event_lines(e)))

    def test_stable_uid_on_reschedule(self):
        e=event()
        uid=cal.event_uid(e)
        e["name"]="Jets v Dolphins"
        e["start"]["localDate"]="2027-12-12"
        self.assertEqual(cal.event_uid(e),uid)
        self.assertNotEqual(uid,cal.event_uid(e,all_events=True))


class SourceResilience(unittest.TestCase):
    def test_retries_temporary_api_failure(self):
        bad=mock.Mock(status_code=503)
        good=mock.Mock(status_code=200)
        good.raise_for_status.return_value=None
        good.json.return_value={"ok":True}
        session=mock.Mock()
        session.get.side_effect=[bad,good]
        with mock.patch.object(fetch.time,"sleep") as sleep:
            self.assertEqual(fetch.api_get(session,"key","venues.json"),{"ok":True})
        self.assertEqual(session.get.call_count,2)
        sleep.assert_called_once()

    def test_missing_and_partial_pages_fail(self):
        failures=({}, {"_embedded":{"events":[]},"page":{"number":0,
            "totalPages":1,"totalElements":2}},
            {"_embedded":{"events":[{"id":"one"}]},
             "page":{"number":0,"totalPages":1,"totalElements":2}},
            {"_embedded":{"events":"malformed"},
             "page":{"number":0,"totalPages":1,"totalElements":1}})
        for response in failures:
            with self.subTest(response=response):
                with mock.patch.object(fetch,"api_get",return_value=response):
                    with self.assertRaises(RuntimeError):
                        fetch.fetch_events(mock.Mock(),"key","venue")

    def test_deduplicates_api_records(self):
        response={"_embedded":{"events":[{"id":"same"},{"id":"same"}]},
                  "page":{"number":0,"totalPages":1,"totalElements":2}}
        with mock.patch.object(fetch,"api_get",return_value=response):
            self.assertEqual(len(fetch.fetch_events(mock.Mock(),"key","venue")),1)

    def test_rejects_mass_disappearance_but_not_small_change(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"all.ics"
            events=[event(f"Band {i}",ident=str(i),segment="Music") for i in range(8)]
            snapshot(path,events,all_events=True)
            with self.assertRaises(RuntimeError):
                check_source.validate_source({"events":events[:2],"eventCount":2},path)
            check_source.validate_source({"events":events[:6],"eventCount":6},path)

    def test_rejects_source_duplicate_ids(self):
        with self.assertRaises(ValueError):
            check_source.validate_source({"events":[event(ident="x"),event(ident="x")],
                                          "eventCount":2},"not-found.ics")


class RetentionAndICS(unittest.TestCase):
    def test_future_grace_does_not_churn_ics(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"all.ics"
            a=event(ident="missing")
            b=event(ident="still-here")
            snapshot(path,[a,b],all_events=True)
            snapshot(path,[b],all_events=True)
            once=path.read_bytes()
            self.assertIn(b"X-METLIFE-MISSING-SINCE",once)
            snapshot(path,[b],all_events=True)
            self.assertEqual(path.read_bytes(),once)
            snapshot(path,[a,b],all_events=True)
            self.assertNotIn(b"X-METLIFE-MISSING-SINCE",path.read_bytes())

    def test_cancelled_or_filtered_event_not_revived(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"all.ics"
            a=event(ident="x")
            b=event(ident="y")
            snapshot(path,[a,b],all_events=True)
            a["status"]="cancelled"
            snapshot(path,[a,b],all_events=True)
            self.assertNotIn("metlife-all-x@",path.read_text())

    def test_future_grace_expires(self):
        stale=(datetime.now(timezone.utc)-timedelta(hours=50)).strftime("%Y%m%dT%H%M%SZ")
        block=cal.build_event_lines(event(ident="x"),all_events=True)
        block.insert(-1,"X-METLIFE-MISSING-SINCE:"+stale)
        self.assertIsNone(cal.retain_temporarily_missing_upcoming(block,datetime.now(NY)))

    def test_seven_day_history_cache(self):
        today=datetime.now(NY).date()
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"all.ics"
            recent=event("Recent Concert",ident="recent",segment="Music",
                         local=today-timedelta(days=3))
            old=event("Old Concert",ident="old",segment="Music",
                      local=today-timedelta(days=10))
            active=event(ident="active")
            snapshot(path,[recent,old,active],all_events=True)
            snapshot(path,[active],all_events=True)
            self.assertIn("metlife-all-recent@",path.read_text())
            self.assertNotIn("metlife-all-old@",path.read_text())

    def test_both_feeds_validate_and_catch_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            events=[event(ident="jet"),event("Giants vs Eagles",ident="giant",
                 attractions=["New York Giants","Philadelphia Eagles"]),
                 event("AC/DC",ident="concert",segment="Music",genre="Rock")]
            snapshot(d/validate_ics.FEEDS[0],events,all_events=False)
            snapshot(d/validate_ics.FEEDS[1],events,all_events=True)
            self.assertEqual(validate_ics.validate_both(d),(2,3))
            path=d/validate_ics.FEEDS[0]
            path.write_bytes(path.read_bytes().replace(b"\r\n",b"\n"))
            with self.assertRaises(ValueError):
                validate_ics.validate_both(d)


if __name__ == "__main__":
    unittest.main()
