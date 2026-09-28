# MetLife Stadium Calendar

Automatically generated iCalendar feeds for events at MetLife Stadium in East Rutherford, New Jersey.

The calendars are updated twice daily using the Ticketmaster Discovery API and published through GitHub Pages.

## Calendar Feeds

### MetLife Stadium Events

Designed for someone who already subscribes to the official New York Giants calendar and a separate NFL postseason calendar.

Includes:

- New York Jets regular-season and preseason games at MetLife Stadium
- Concerts
- College football
- Soccer
- Wrestling
- Other legitimate public events at MetLife Stadium

Excludes:

- New York Giants games
- NFL postseason games
- Stadium tours
- Parking-only listings
- Season-ticket listings
- Suite, hospitality, premium-seating, and similar ancillary Ticketmaster listings

Subscription URL:

https://mmalinconico.github.io/metlife-stadium-calendar/metlife-stadium-calendar.ics

### MetLife Stadium All Events

Includes all legitimate public events at MetLife Stadium, including New York Giants games and NFL postseason games.

Still excludes non-event or ancillary listings such as stadium tours, parking, season tickets, suites, hospitality packages, and similar Ticketmaster products.

Subscription URL:

https://mmalinconico.github.io/metlife-stadium-calendar/metlife-stadium-all-events.ics

## Event Retention

Completed events remain in both calendars for approximately 7 days before being removed.

Because Ticketmaster may stop returning an event shortly after it occurs, the generator also uses the previously published calendar as a short-term historical cache so recent completed events remain available.

## Updates

A GitHub Actions workflow runs twice daily and can also be run manually.

The workflow:

1. Fetches MetLife Stadium events from the Ticketmaster Discovery API.
2. Removes ancillary and non-event listings.
3. Generates both calendar feeds.
4. Validates both `.ics` files.
5. Commits updated calendar files only when their contents change.

## Calendar Details

- Time zone: `America/New_York`
- Location: `MetLife Stadium`
- Timed events use the published Ticketmaster start time.
- Events with a known date but no confirmed start time are created as all-day events.
- Sports events use a 3-hour duration.
- Concerts end at 11:00 PM local time when possible.
- Other timed events default to a 4-hour duration.
- Stable event IDs are used so updates modify existing calendar entries rather than creating duplicates.

## Source

Event data is provided by the Ticketmaster Discovery API.

GitHub Pages hosts the generated `.ics` subscription feeds.
