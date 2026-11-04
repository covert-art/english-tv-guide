#!/usr/bin/env python3
"""Builds an English-only copy of the Free-TV playlist and a small guide that matches it.

Usage: build.py [--out DIR] [--base-url URL] [--report]
Writes english.m3u8 and guide.xml.gz to DIR. Standard library only, plus curl.
"""
import argparse
import collections
import datetime
import gzip
import html
import json
import os
import re
import subprocess
import sys
import tempfile

PLAYLIST_URL = "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlist.m3u8"
GUIDE_URL = "https://epgshare01.online/epgshare01/epg_ripper_%s.xml.gz"
HERE = os.path.dirname(os.path.abspath(__file__))
GUIDE_HOURS_BACK = 3
GUIDE_DAYS_AHEAD = 2

# The guide files to try for each playlist group, most fitting first.
GROUPS = {
    "USA": ["US2", "PLEX1"],
    "UK": ["UK1", "IE1"],
    "Ireland": ["IE1", "UK1"],
    "Canada": ["CA2"],
    "Australia": ["AU1"],
    "New Zealand": ["NZ1"],
    "Kenya": ["KE1"],
    "Nigeria": ["NG1"],
    "News": ["US2", "UK1", "PLEX1", "CA2", "AU1", "SG1"],
    "Business": ["US2", "UK1", "PLEX1"],
    "Documentaries (EN)": ["US2", "PLEX1", "UK1"],
    "Music (EN)": ["UK1", "US2", "PLEX1"],
}

NOISE = re.compile(r"\b(hd|fhd|uhd|sd|tv|channel|east|west|eastern|stream|us|usa|uk|the|national|network|live|now)\b")


def fetch(url):
    return subprocess.run(
        ["curl", "-fsSL", "--retry", "3", "--retry-all-errors", "--max-time", "180", url],
        check=True, stdout=subprocess.PIPE,
    ).stdout


def norm(name):
    s = html.unescape(name).lower().replace("&", "and")
    s = re.sub(r"[ⓈⓎⒼ]|\(.*?\)|\[.*?\]", "", s)
    return re.sub(r"[^a-z0-9]", "", NOISE.sub("", s))


def read_playlist(text):
    lines = text.split("\n")
    rows = []
    for i, line in enumerate(lines):
        if not line.startswith("#EXTINF") or i + 1 >= len(lines):
            continue
        group = re.search(r'group-title="([^"]*)"', line)
        url = lines[i + 1].strip()
        if group and group.group(1) in GROUPS and url.startswith("http"):
            rows.append({"group": group.group(1), "name": line.rsplit(",", 1)[-1].strip(), "url": url, "info": line})
    return rows


def read_guide(path):
    """Returns ({normalised name: channel id}, {channel id: its <channel> block}, programme count per id)."""
    data = gzip.open(path).read().decode("utf8", "replace")
    counts = collections.Counter(re.findall(r'<programme [^>]*channel="([^"]*)"', data))
    names, blocks = {}, {}
    for m in re.finditer(r'<channel [^>]*id="([^"]*)"[^>]*>.*?</channel>', data, re.S):
        cid = m.group(1)
        if not counts[cid]:
            continue
        blocks[cid] = m.group(0)
        labels = re.findall(r"<display-name[^>]*>([^<]*)", m.group(0))
        labels.append(cid.rsplit(".", 1)[0].replace(".", " "))
        for label in labels:
            key = norm(label)
            if key:
                names.setdefault(key, cid)
    return data, names, blocks


def match_channels(rows, config, guides):
    """Sets row["guide"] to (file, channel id) where a channel has listings; config overrides win."""
    for row in rows:
        row["guide"] = None
        name = row["name"]
        if name in config["no_guide"]:
            continue
        if name in config["match"]:
            guide_file, cid = config["match"][name]
            if cid in guides[guide_file][2]:
                row["guide"] = (guide_file, cid)
            continue
        key = norm(name)
        for guide_file in GROUPS[row["group"]]:
            cid = guides[guide_file][1].get(key)
            if cid:
                row["guide"] = (guide_file, cid)
                break


def write_playlist(path, rows, base_url):
    out = ['#EXTM3U x-tvg-url="%s/guide.xml.gz"' % base_url if base_url else "#EXTM3U"]
    for row in rows:
        info = row["info"]
        if row["guide"]:
            cid = html.unescape(row["guide"][1])
            if 'tvg-id="' in info:
                info = re.sub(r'tvg-id="[^"]*"', lambda _: 'tvg-id="%s"' % cid, info)
            else:
                info = info.replace("#EXTINF:-1", '#EXTINF:-1 tvg-id="%s"' % cid, 1)
        out += [info, row["url"]]
    with open(path, "w", encoding="utf8") as f:
        f.write("\n".join(out) + "\n")


def write_guide(path, rows, guides):
    now = datetime.datetime.now(datetime.timezone.utc)
    start = (now - datetime.timedelta(hours=GUIDE_HOURS_BACK)).strftime("%Y%m%d%H%M%S")
    stop = (now + datetime.timedelta(days=GUIDE_DAYS_AHEAD)).strftime("%Y%m%d%H%M%S")
    wanted = {row["guide"] for row in rows if row["guide"]}
    programmes = 0
    with gzip.open(path, "wt", encoding="utf8") as out:
        out.write('<?xml version="1.0" encoding="UTF-8"?>\n<tv generator-info-name="english-tv-guide">\n')
        for guide_file, cid in sorted(wanted):
            out.write(guides[guide_file][2][cid] + "\n")
        for guide_file in sorted({g for g, _ in wanted}):
            ids = {c for g, c in wanted if g == guide_file}
            for m in re.finditer(r'<programme ([^>]*)>.*?</programme>', guides[guide_file][0], re.S):
                channel = re.search(r'channel="([^"]*)"', m.group(1))
                begin = re.search(r'start="(\d{14})', m.group(1))
                end = re.search(r'stop="(\d{14})', m.group(1))
                if channel and channel.group(1) in ids and begin and end and end.group(1) > start and begin.group(1) < stop:
                    out.write(m.group(0) + "\n")
                    programmes += 1
        out.write("</tv>\n")
    return programmes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="out")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()

    with open(os.path.join(HERE, "config.json"), encoding="utf8") as f:
        config = json.load(f)
    exclude = re.compile(config["exclude"], re.I)
    dead = set(config["exclude_urls"])
    rows = [
        r for r in read_playlist(fetch(PLAYLIST_URL).decode("utf8", "replace"))
        if not exclude.search(r["name"]) and r["url"] not in dead
    ]

    guide_files = sorted({g for files in GROUPS.values() for g in files} | {v[0] for v in config["match"].values()})
    guides = {}
    with tempfile.TemporaryDirectory() as tmp:
        for guide_file in guide_files:
            path = os.path.join(tmp, guide_file + ".gz")
            with open(path, "wb") as f:
                f.write(fetch(GUIDE_URL % guide_file))
            guides[guide_file] = read_guide(path)

    match_channels(rows, config, guides)
    os.makedirs(args.out, exist_ok=True)
    write_playlist(os.path.join(args.out, "english.m3u8"), rows, args.base_url)
    programmes = write_guide(os.path.join(args.out, "guide.xml.gz"), rows, guides)

    matched = sum(1 for r in rows if r["guide"])
    print("%d channels, %d with listings, %d programmes" % (len(rows), matched, programmes))
    if len(rows) < 50 or matched < 20 or programmes < 500:
        sys.exit("Refusing to publish: the result is much smaller than expected")
    if args.report:
        for row in sorted(rows, key=lambda r: (r["group"], r["name"])):
            print("%-10s %-30s %s" % (row["group"][:10], row["name"][:30], " ".join(row["guide"]) if row["guide"] else "-"))


if __name__ == "__main__":
    main()
