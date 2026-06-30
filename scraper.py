#!/usr/bin/env python3
"""
South East Seneca Live Music Scraper
Fetches events from southeastseneca.com/events and merges into events.json
Run automatically every Monday via GitHub Actions.
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import sys
from datetime import date, datetime

# Normalize venue names from SES website to canonical names used in index.html LOGOS dict
VENUE_MAP = {
    "Grist Iron Brewing Company": "Grist Iron Brewing",
    "Two Goats Brewing, LLC": "Two Goats Brewing",
    "Two Goats Brewing": "Two Goats Brewing",
    "Hazlitt 1852 Vineyards": "Hazlitt 1852 Vineyards",
    "Wagner Vineyards Estate Winery": "Wagner Vineyards",
    "Wagner Vineyards": "Wagner Vineyards",
    "Scale House Brewery": "Scale House Brewery",
    "Solera Taphouse": "Solera Taphouse",
    "Solera Tap House": "Solera Taphouse",
    "Lucky Hare Brewing": "Lucky Hare Brewing",
    "Lucky Hare Brewing Company": "Lucky Hare Brewing",
    "Rasta Ranch Vineyards": "Rasta Ranch Vineyards",
    "Idol Ridge Winery": "Idol Ridge Winery",
    "Either Oar": "Either Oar",
    "Stonecat Cafe": "Stonecat Café",
    "Stonecat Café": "Stonecat Café",
    "Forge Cellars": "Forge Cellars",
    "Atwater Vineyards": "Atwater Vineyards",
    "Damiani Cellars": "Damiani Cellars",
    "Damiani Wine Cellars": "Damiani Cellars",
    "Hillick & Hobbs Wine Estate": "Hillick & Hobbs",
    "Hillick & Hobbs": "Hillick & Hobbs",
    "Hillick and Hobbs": "Hillick & Hobbs",
    "Sawmill Creek": "Sawmill Creek",
}

VENUE_URLS = {
    "Grist Iron Brewing": "https://www.gristironbrewing.com",
    "Two Goats Brewing": "https://www.twogoatsbrewing.com",
    "Hazlitt 1852 Vineyards": "https://www.hazlitt1852.com",
    "Wagner Vineyards": "https://www.wagnervineyards.com",
    "Scale House Brewery": "https://www.scalehousebrews.com",
    "Solera Taphouse": "https://www.solerataphouse.com",
    "Lucky Hare Brewing": "https://www.luckyharebrewing.com",
    "Rasta Ranch Vineyards": "https://www.rastaranchvineyards.com",
    "Idol Ridge Winery": "https://www.idolridge.com",
    "Either Oar": "https://www.eitheroar.com",
    "Stonecat Café": "https://www.stonecatcafe.com",
    "Forge Cellars": "https://www.forgecellars.com",
    "Atwater Vineyards": "https://www.atwatervineyards.com",
    "Damiani Cellars": "https://www.damianiwinecellars.com",
    "Hillick & Hobbs": "https://www.hillickandhobbs.com",
    "Sawmill Creek": "https://www.sawmillcreekestate.com",
}


def format_time_range(start_str, end_str):
    """Convert '5:00 PM' + '8:00 PM' → '5–8 PM'"""
    def parse_t(s):
        m = re.match(r'(\d+)(?::(\d+))?\s*(AM|PM)', s.strip(), re.I)
        if not m:
            return None
        return int(m.group(1)), int(m.group(2) or 0), m.group(3).upper()

    s = parse_t(start_str)
    e = parse_t(end_str)
    if not s or not e:
        return f"{start_str.strip()}–{end_str.strip()}"

    def fmt(h, mi):
        return f"{h}" if mi == 0 else f"{h}:{mi:02d}"

    if s[2] == e[2]:
        return f"{fmt(s[0], s[1])}–{fmt(e[0], e[1])} {s[2]}"
    return f"{fmt(s[0], s[1])} {s[2]}–{fmt(e[0], e[1])} {e[2]}"


def parse_event(article):
    """Parse a single Squarespace event article element."""
    try:
        # --- Date ---
        time_el = article.select_one("time[datetime]")
        if not time_el:
            return None
        dt_raw = time_el.get("datetime", "")[:10]   # e.g. "2026-06-30"
        if not re.match(r"\d{4}-\d{2}-\d{2}", dt_raw):
            return None
        event_date = dt_raw

        # --- Title / artist ---
        title_el = article.select_one(
            "h1.eventlist-title a, h1.eventlist-title, "
            ".eventlist-event--title a, .eventlist-event--title"
        )
        title = title_el.get_text(strip=True) if title_el else ""
        event_url = ""
        if title_el and title_el.name == "a":
            href = title_el.get("href", "")
            event_url = ("https://www.southeastseneca.com" + href
                         if href.startswith("/") else href)

        # --- Venue ---
        venue_el = article.select_one(
            "address, .eventlist-meta-address, "
            "[class*='address'], .eventlist-meta-item--location"
        )
        raw_venue = ""
        if venue_el:
            raw_venue = venue_el.get_text(separator=" ", strip=True)
            raw_venue = re.sub(r"\(map\)", "", raw_venue).strip()
            # Strip trailing map link text
            raw_venue = re.split(r"\s{2,}", raw_venue)[0].strip()

        venue = VENUE_MAP.get(raw_venue, raw_venue)
        if not venue:
            return None

        # --- Time ---
        time_text = ""
        for sel in [
            ".eventlist-meta-time",
            "[class*='event-time']",
            ".eventlist-meta-item--time",
        ]:
            t = article.select_one(sel)
            if t:
                time_text = t.get_text(strip=True)
                break

        # Fallback: scan all <li> for a time pattern
        if not time_text:
            for li in article.select("li"):
                txt = li.get_text(strip=True)
                if re.search(r"\d+:\d+\s*(AM|PM)", txt, re.I):
                    time_text = txt
                    break

        formatted_time = time_text
        # Try "5:00 PM – 8:00 PM" or "5:00 PM 8:00 PM"
        m = re.search(
            r"(\d+:\d+\s*(?:AM|PM))\s*[–\-]?\s*(\d+:\d+\s*(?:AM|PM))",
            time_text, re.I
        )
        if m:
            formatted_time = format_time_range(m.group(1), m.group(2))

        # --- Artist: strip venue from title ---
        artist = title
        for strip_venue in [raw_venue, venue]:
            if strip_venue:
                artist = re.sub(
                    rf"\s*[@at]+\s*{re.escape(strip_venue)}\s*$", "",
                    artist, flags=re.I
                ).strip()

        url = VENUE_URLS.get(venue, event_url or "https://www.southeastseneca.com/events")

        return {
            "date": event_date,
            "venue": venue,
            "artist": artist,
            "time": formatted_time or "TBD",
            "url": url,
        }

    except Exception as exc:
        print(f"  ⚠ Error parsing event: {exc}")
        return None


def fetch_ses_events():
    """Scrape all events from southeastseneca.com/events (handles pagination)."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SES-Music-Bot/1.0)"}
    url = "https://www.southeastseneca.com/events"
    all_events = []
    seen_urls = set()

    while url:
        print(f"  Fetching {url}")
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        articles = (
            soup.select("article.eventlist-event") or
            soup.select(".eventlist-event") or
            soup.select("[class*='eventlist-event']")
        )
        print(f"  Found {len(articles)} events on page")

        for art in articles:
            ev = parse_event(art)
            if ev:
                key = f"{ev['date']}|{ev['venue']}|{ev['artist'][:30]}"
                if key not in seen_urls:
                    seen_urls.add(key)
                    all_events.append(ev)

        # Pagination
        next_a = soup.select_one(
            "a.eventlist-button-loadmore, "
            ".eventlist--pagination .next a, "
            "[rel='next']"
        )
        url = None
        if next_a and next_a.get("href"):
            href = next_a["href"]
            url = ("https://www.southeastseneca.com" + href
                   if href.startswith("/") else href)

    return all_events


def fetch_venue_site_events(base_url, venue_name, venue_url):
    """Scrape a venue's own Squarespace events page (same format as SES)."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SES-Music-Bot/1.0)"}
    url = base_url
    all_events = []
    seen = set()

    while url:
        print(f"  Fetching {url}")
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        articles = (
            soup.select("article.eventlist-event") or
            soup.select(".eventlist-event") or
            soup.select("[class*='eventlist-event']")
        )
        print(f"  Found {len(articles)} events")

        for art in articles:
            # Date
            time_el = art.select_one("time[datetime]")
            if not time_el:
                continue
            dt_raw = time_el.get("datetime", "")[:10]
            if not re.match(r"\d{4}-\d{2}-\d{2}", dt_raw):
                continue

            # Title = artist
            title_el = art.select_one(
                "h1.eventlist-title a, h1.eventlist-title, "
                ".eventlist-event--title a, .eventlist-event--title"
            )
            if not title_el:
                continue
            artist = title_el.get_text(strip=True)
            # Strip "@ Venue Name" or "at Venue Name" suffix if present
            artist = re.sub(rf"\s*[@at]+\s*{re.escape(venue_name)}\s*$", "", artist, flags=re.I).strip()

            # Time
            time_text = ""
            for sel in [".eventlist-meta-time", "[class*='event-time']", ".eventlist-meta-item--time"]:
                t = art.select_one(sel)
                if t:
                    time_text = t.get_text(strip=True)
                    break
            if not time_text:
                for li in art.select("li"):
                    txt = li.get_text(strip=True)
                    if re.search(r"\d+:\d+\s*(AM|PM)", txt, re.I):
                        time_text = txt
                        break

            formatted_time = time_text
            m = re.search(r"(\d+:\d+\s*(?:AM|PM))\s*[–\-]?\s*(\d+:\d+\s*(?:AM|PM))", time_text, re.I)
            if m:
                formatted_time = format_time_range(m.group(1), m.group(2))

            key = f"{dt_raw}|{artist[:30]}"
            if key not in seen:
                seen.add(key)
                all_events.append({
                    "date": dt_raw,
                    "venue": venue_name,
                    "artist": artist,
                    "time": formatted_time or "TBD",
                    "url": venue_url,
                })

        # Pagination
        next_a = soup.select_one(
            "a.eventlist-button-loadmore, .eventlist--pagination .next a, [rel='next']"
        )
        url = None
        if next_a and next_a.get("href"):
            href = next_a["href"]
            domain = "/".join(base_url.split("/")[:3])
            url = (domain + href if href.startswith("/") else href)

    return all_events


def fetch_damiani_events():
    """Scrape Damiani Wine Cellars events (WordPress/The Events Calendar format)."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SES-Music-Bot/1.0)"}
    all_events = []

    # Try WordPress REST API first — much cleaner than scraping HTML
    try:
        api_url = "https://damianiwinecellars.com/wp-json/tribe/events/v1/events?per_page=50&status=publish"
        resp = requests.get(api_url, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            events_list = data.get("events", [])
            print(f"  Found {len(events_list)} events via Damiani API")
            for ev in events_list:
                title = re.sub(r'<[^>]+>', '', ev.get("title", "")).strip()
                # Skip non-music events
                if not any(kw in title.lower() for kw in ["music", "blues", "jazz", "bocce", "bollicine", "band", "live"]):
                    continue
                start = ev.get("start_date", "")[:10]  # "2026-07-01"
                time_start = ev.get("start_date", "")[11:16]  # "17:30"
                time_end = ev.get("end_date", "")[11:16]      # "20:00"
                if time_start and time_end:
                    def fmt24(t):
                        h, m = int(t[:2]), int(t[3:])
                        suffix = "AM" if h < 12 else "PM"
                        h = h % 12 or 12
                        return f"{h}" if m == 0 else f"{h}:{m:02d}"
                    s_suffix = "AM" if int(time_start[:2]) < 12 else "PM"
                    e_suffix = "AM" if int(time_end[:2]) < 12 else "PM"
                    s = fmt24(time_start)
                    e = fmt24(time_end)
                    if s_suffix == e_suffix:
                        time_str = f"{s}–{e} {s_suffix}"
                    else:
                        time_str = f"{s} {s_suffix}–{e} {e_suffix}"
                else:
                    time_str = "TBD"
                if start:
                    all_events.append({
                        "date": start,
                        "venue": "Damiani Cellars",
                        "artist": title,
                        "time": time_str,
                        "url": "https://www.damianiwinecellars.com",
                    })
            return all_events
    except Exception:
        pass  # Fall through to HTML scraping

    # Fallback: scrape HTML events page
    print("  Damiani API unavailable, falling back to HTML scrape")
    resp = requests.get("https://damianiwinecellars.com/events/", headers=headers, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    month_names = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
                   "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}

    for article in soup.select("article.type-tribe_events, .tribe-events-calendar-list__event, article"):
        title_el = article.select_one("h3 a, h2 a, .tribe-event-url")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        if not any(kw in title.lower() for kw in ["music","blues","jazz","bocce","bollicine","band","live"]):
            continue

        # Date from abbr or time element
        date_str = ""
        abbr = article.select_one("abbr[title]")
        if abbr:
            date_str = abbr.get("title", "")[:10]
        if not date_str:
            time_el = article.select_one("time[datetime]")
            if time_el:
                date_str = time_el.get("datetime", "")[:10]
        if not date_str:
            # Try parsing "DD Mon" text pattern
            text = article.get_text()
            m = re.search(r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', text)
            if m:
                day, mon = int(m.group(1)), month_names[m.group(2)]
                year = date.today().year
                date_str = f"{year}-{mon:02d}-{day:02d}"
        if not date_str:
            continue

        # Time
        time_text = ""
        for sel in [".tribe-event-schedule-details", ".tribe-events-schedule", "[class*='time']"]:
            t = article.select_one(sel)
            if t:
                time_text = t.get_text(strip=True)
                break
        if not time_text:
            m = re.search(r'\d+:\d+\s*(am|pm)\s*[-–]\s*\d+:\d+\s*(am|pm)', article.get_text(), re.I)
            if m:
                time_text = m.group(0)

        all_events.append({
            "date": date_str,
            "venue": "Damiani Cellars",
            "artist": title,
            "time": time_text or "5:30–8 PM",
            "url": "https://www.damianiwinecellars.com",
        })

    print(f"  Found {len(all_events)} Damiani events via HTML")
    return all_events


# Additional venue sites to scrape (not always listed on SES)
EXTRA_VENUES = [
    {
        "url": "https://www.gristironbrewing.com/events-live-music",
        "name": "Grist Iron Brewing",
        "site": "https://www.gristironbrewing.com",
    },
    {
        "url": "https://twogoatsbrewing.com/music-events",
        "name": "Two Goats Brewing",
        "site": "https://www.twogoatsbrewing.com",
    },
]


def event_key(e):
    return (e["date"], e["venue"].lower().strip(), e["artist"][:25].lower().strip())


def main():
    events_path = "events.json"
    today = date.today().isoformat()

    # Load existing events
    try:
        with open(events_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        print(f"Loaded {len(existing)} existing events from {events_path}")
    except FileNotFoundError:
        print(f"{events_path} not found — starting fresh")
        existing = []

    existing_keys = {event_key(e) for e in existing}

    all_scraped = []

    # Fetch from SES aggregator
    print("\nScraping SES events page...")
    try:
        ses_events = fetch_ses_events()
        print(f"Scraped {len(ses_events)} events from SES\n")
        all_scraped.extend(ses_events)
    except Exception as exc:
        print(f"ERROR fetching SES page: {exc}")

    # Fetch from individual venue sites
    for v in EXTRA_VENUES:
        print(f"\nScraping {v['name']} events page...")
        try:
            venue_events = fetch_venue_site_events(v["url"], v["name"], v["site"])
            print(f"Scraped {len(venue_events)} events from {v['name']}\n")
            all_scraped.extend(venue_events)
        except Exception as exc:
            print(f"ERROR fetching {v['name']} page: {exc}")

    # Fetch from Damiani (WordPress format — separate parser)
    print("\nScraping Damiani Wine Cellars events...")
    try:
        damiani_events = fetch_damiani_events()
        print(f"Scraped {len(damiani_events)} events from Damiani\n")
        all_scraped.extend(damiani_events)
    except Exception as exc:
        print(f"ERROR fetching Damiani events: {exc}")

    if not all_scraped:
        print("No events scraped from any source — aborting to avoid data loss.")
        sys.exit(1)

    # Merge: add new future events not already present
    added = 0
    for ev in all_scraped:
        if ev["date"] < today:
            continue  # skip past events
        k = event_key(ev)
        if k not in existing_keys:
            existing.append(ev)
            existing_keys.add(k)
            added += 1
            print(f"  + {ev['date']}  {ev['venue']}  —  {ev['artist']}")

    print(f"\n{added} new event(s) added")

    # Sort all events by date then venue
    existing.sort(key=lambda e: (e["date"], e["venue"]))

    # Write back
    with open(events_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(existing)} events to {events_path}")


if __name__ == "__main__":
    main()
