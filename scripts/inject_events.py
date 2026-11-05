#!/usr/bin/env python3
"""
Injects events.json into the `const EVENTS = [...]` array in index.html.
events.json is the single source of truth; index.html stays self-contained
so the same file works on GitHub Pages and as a Cowork artifact.
"""
import json, io, re, sys
from datetime import datetime, timedelta

HTML = "index.html"
JSON_PATH = "events.json"

def monday_of(d):
    dt = datetime.strptime(d, "%Y-%m-%d")
    return (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")

def week_label(mon):
    a = datetime.strptime(mon, "%Y-%m-%d")
    b = a + timedelta(days=6)
    if a.month == b.month:
        return "%s %d–%d" % (a.strftime("%b"), a.day, b.day)
    return "%s %d – %s %d" % (a.strftime("%b"), a.day, b.strftime("%b"), b.day)

def esc(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')

def main():
    events = json.load(io.open(JSON_PATH, encoding="utf-8"))
    events.sort(key=lambda e: (e["date"], e["venue"]))

    lines, current = [], None
    for e in events:
        mon = monday_of(e["date"])
        if mon != current:
            if current is not None:
                lines.append("")
            lines.append("  // Week of %s" % week_label(mon))
            current = mon
        lines.append(
            '  {date:"%s", venue:"%s", artist:"%s", time:"%s", url:"%s"},'
            % (esc(e["date"]), esc(e["venue"]), esc(e["artist"]),
               esc(e.get("time", "")), esc(e.get("url", "")))
        )

    block = "const EVENTS = [\n" + "\n".join(lines) + "\n];"
    src = io.open(HTML, encoding="utf-8").read()
    new, n = re.subn(r"const EVENTS = \[[\s\S]*?\];", lambda m: block, src, count=1)
    if n != 1:
        sys.exit("ERROR: could not locate the EVENTS array in %s" % HTML)
    io.open(HTML, "w", encoding="utf-8").write(new)
    print("Injected %d events into %s" % (len(events), HTML))

if __name__ == "__main__":
    main()
