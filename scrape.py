#!/usr/bin/env python3
"""Scrape live parking availability from hollywoodburbankairport.com/parking/.

Uses only the Python standard library so it runs anywhere (including a bare
GitHub Actions runner) with no pip installs. Writes data/parking.json.
"""

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

URL = "https://www.hollywoodburbankairport.com/parking/"
DATA_DIR = Path(__file__).parent / "data"
OUT = DATA_DIR / "parking.json"
SPEECH_OUT = DATA_DIR / "speech.txt"

# Matches "Parking Lot C ... Spaces Available ... 48" and
# "Structure: Level 1 ... Spaces Available ... 31" in the page's visible text.
LOT_PATTERN = re.compile(
    r"(Parking Lot [A-Z]|Structure:?\s*Level \d)"  # lot name
    r"\s*Spaces\s*Available\s*"                    # label between name and count
    r"(\d+|FULL|OPEN|CLOSED)",                     # count or status word
    re.IGNORECASE,
)


class TextExtractor(HTMLParser):
    """Strips tags and returns the page's visible text."""

    SKIP = {"script", "style", "noscript"}

    def __init__(self):
        super().__init__()
        self.chunks = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            self.chunks.append(data)

    def text(self):
        return re.sub(r"\s+", " ", " ".join(self.chunks))


def fetch_html(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            # Some WordPress hosts reject the default Python User-Agent.
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_lots(html: str) -> dict:
    extractor = TextExtractor()
    extractor.feed(html)
    text = extractor.text()

    lots = {}
    for name, value in LOT_PATTERN.findall(text):
        name = re.sub(r"\s+", " ", name).strip()
        # Normalize "Structure Level 1" -> "Structure: Level 1"
        name = re.sub(r"^Structure:?\s*", "Structure: ", name)
        lots[name] = int(value) if value.isdigit() else value.upper()
    return lots


def spoken_name(name: str) -> str:
    """'Parking Lot C' -> 'Lot C', 'Structure: Level 2' -> 'the structure level 2'."""
    if name.startswith("Structure"):
        return "the structure " + name.replace("Structure: ", "").lower()
    return name.replace("Parking ", "")


def build_speech(lots: dict) -> str:
    """One Siri-friendly paragraph summarizing availability."""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%-I:%M %p")
        prefix = f"As of {now} at Burbank airport: "
    except Exception:
        prefix = "At Burbank airport: "

    numeric = {k: v for k, v in lots.items() if isinstance(v, int)}
    parts = []
    if numeric:
        best = max(numeric, key=numeric.get)
        parts.append(f"{spoken_name(best)} has the most spaces with {numeric[best]}")
    for name, value in lots.items():
        if numeric and name == max(numeric, key=numeric.get):
            continue
        if isinstance(value, int):
            parts.append(f"{spoken_name(name)} has {value}")
        else:
            parts.append(f"{spoken_name(name)} is {value.lower()}")
    return prefix + ". ".join(parts) + "."


def main() -> int:
    html = fetch_html(URL)
    lots = parse_lots(html)

    if not lots:
        print("ERROR: no lots parsed - page layout may have changed.", file=sys.stderr)
        return 1  # non-zero exit keeps the last good JSON committed

    payload = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": URL,
        "lots": lots,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    SPEECH_OUT.write_text(build_speech(lots) + "\n")
    print(f"Wrote {OUT} with {len(lots)} lots: {lots}")
    print(f"Wrote {SPEECH_OUT}: {SPEECH_OUT.read_text().strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
