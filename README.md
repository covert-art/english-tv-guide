# English TV Guide

An English-only copy of the [Free-TV playlist](https://github.com/Free-TV/IPTV) with a small guide that matches it, rebuilt daily for TV Hub.

- Playlist: `https://raw.githubusercontent.com/covert-art/english-tv-guide/data/english.m3u8`
- Guide: `https://raw.githubusercontent.com/covert-art/english-tv-guide/data/guide.xml.gz`

The playlist names the guide in its header, so adding the playlist is enough.

## How it works

`build.py` keeps the English groups, drops the entries in `config.json`, and points each channel at its listings in the [epgshare01](https://epgshare01.online/) guide files. Most matches are by channel name; `config.json` holds the ones set by hand.

## Changing it

Edit `config.json`:

- `exclude`: channel names to drop
- `exclude_urls`: streams to drop
- `match`: a channel's guide file and guide ID
- `no_guide`: channels that should have no listings

Then run the workflow from the Actions tab, or wait for the daily run. To test locally: `python3 build.py --report`.

The streams and listings belong to their owners. This repo only holds links and schedule data.
