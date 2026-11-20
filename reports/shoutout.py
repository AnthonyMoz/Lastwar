"""Make a "keep going" graphic for commanders active in the recent uploads.

Usage: python reports/shoutout.py [--minutes 60] [--out reports/out]

lastwar.farm VS scores have no timestamps, so every run saves a snapshot of
everyone's VS score for the day (reports/out/vs_snapshots/<day>/<HHMM>.json,
keyed by the last phone sync time). The graphic compares the latest data with
each member's earliest snapshot in the last --minutes, and also counts anyone
whose Total Hero Power was uploaded in that window (heroes changed, so they
are online). Writes
shoutout_<date>.html; render with reports/render.js.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lastwar_farm import LastWarFarmClient  # noqa: E402

SERVER_OFFSET = dt.timedelta(hours=2)  # server time is UTC-2; reset is 00:00 server time


def short(n: int, places: int = 1) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.{places}f}M"
    if n >= 100_000:
        return f"{n / 1_000:.0f}K"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K".replace(".0K", "K")
    return f"{n:,}"


def last_sync(client: LastWarFarmClient) -> dt.datetime:
    return max(dt.datetime.fromisoformat(r["recordedAt"].replace("Z", "+00:00"))
               for f in (client.export_power, client.export_kills, client.export_thp)
               for r in f()["data"])


def snapshot(client: LastWarFarmClient, out: Path):
    """Save today's VS scores for every active member; return (day, synced, scores, path)."""
    now = dt.datetime.now(dt.timezone.utc)
    day = (now - SERVER_OFFSET).date()
    synced = last_sync(client)
    members = {m["id"]: m["name"] for m in client.list_members()["data"] if m["status"] == "ACTIVE"}
    scores = {members[d["memberId"]]: int(d["score"]) for d in client.export_duels()["data"]
              if d["scoredOn"] == day.isoformat() and d["memberId"] in members}
    folder = out / "vs_snapshots" / day.isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = (synced - SERVER_OFFSET).strftime("%H%M")
    path = folder / f"{stamp}.json"
    path.write_text(json.dumps({"synced": synced.isoformat(), "taken": now.isoformat(),
                                "scores": scores}, ensure_ascii=False), encoding="utf-8")
    return day, synced, scores, path


def baseline(folder: Path, synced: dt.datetime, minutes: int):
    """Each member's earliest VS score across snapshots in the window, and the window start."""
    start = synced - dt.timedelta(minutes=minutes)
    earliest: dict[str, tuple[dt.datetime, int]] = {}
    first = None
    for f in folder.glob("*.json"):
        snap = json.loads(f.read_text(encoding="utf-8"))
        t = dt.datetime.fromisoformat(snap["synced"])
        if not (start <= t < synced):
            continue
        first = t if first is None or t < first else first
        for name, score in snap["scores"].items():
            if name not in earliest or t < earliest[name][0]:
                earliest[name] = (t, score)
    return first or start, {n: v for n, (_, v) in earliest.items()}


def hero_activity(client: LastWarFarmClient, since: dt.datetime) -> dict[str, dt.datetime]:
    """Members whose Total Hero Power was uploaded since `since` (latest upload time)."""
    names = {m["id"]: m["name"] for m in client.list_members()["data"] if m["status"] == "ACTIVE"}
    seen: dict[str, dt.datetime] = {}
    for r in client.export_thp()["data"]:
        t = dt.datetime.fromisoformat(r["recordedAt"].replace("Z", "+00:00"))
        if t >= since and r["memberId"] in names:
            n = names[r["memberId"]]
            seen[n] = max(t, seen.get(n, t))
    return seen


def render(day, since, synced, rows, vs_min) -> str:
    """rows: (name, vs_gain, vs_today, hero_time or None), most active first."""
    e = html.escape
    since_s = (since - SERVER_OFFSET).strftime("%H:%M")
    sync_s = (synced - SERVER_OFFSET).strftime("%H:%M")
    top = max((g for _, g, _, _ in rows), default=0) or 1
    items = []
    for name, gain, after, hero in rows:
        hit = after >= vs_min
        badge = '<span class="hit">Target hit</span>' if hit else f'<span class="togo">{short(vs_min - after)} to go</span>'
        items.append(
            f'<li><span class="nm">{e(name)}</span>'
            f'<span class="act">'
            + ('<span class="tag vs">VS pushed</span>' if gain else "")
            + (f'<span class="tag hero">Heroes upgraded {(hero - SERVER_OFFSET):%H:%M}</span>' if hero else "")
            + '</span>'
            f'<span class="gain">{"+" + short(gain) if gain else "—"}</span>'
            f'<span class="now">{short(after, 2)} {badge}</span></li>')
    body = "\n".join(items) or '<li class="none">No activity in the recent uploads yet. Be the first.</li>'
    total = sum(g for _, g, _, _ in rows)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Keep Going</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Inter:wght@400;500;600;700&display=swap">
<style>
:root {{ --bg:#11151b; --panel:#1a2029; --line:#2a3340; --fg:#e9edf2; --muted:#9aa6b4;
  --go:#4cc38a; --vs:#e3a63b; --track:#2a3340;
  --head:"Barlow Condensed","Arial Narrow",sans-serif; --body:"Inter","Segoe UI",Arial,sans-serif; }}
* {{ box-sizing:border-box; }} html,body {{ margin:0; background:var(--bg); }}
body {{ width:1080px; color:var(--fg); font-family:var(--body); font-size:22px; line-height:1.35; }}
.page {{ padding:52px 56px 48px; display:flex; flex-direction:column; gap:28px; }}
header {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:24px; align-items:start; }}
.eyebrow {{ font-family:var(--head); font-weight:600; letter-spacing:.14em; text-transform:uppercase; color:var(--go); font-size:24px; }}
h1 {{ font-family:var(--head); font-weight:700; font-size:92px; line-height:.92; margin:6px 0 14px; text-transform:uppercase; }}
h1 span {{ color:var(--go); }}
.lede {{ margin:0; color:var(--muted); font-size:24px; max-width:640px; }} .lede b {{ color:var(--fg); }}
.stat {{ background:var(--go); color:#0e1a14; border-radius:10px; padding:16px 22px; text-align:right; display:flex; flex-direction:column; gap:4px; min-width:250px; }}
.stat .big {{ font-family:var(--head); font-weight:700; font-size:54px; line-height:.95; }}
.stat .lbl {{ font-family:var(--head); font-weight:700; font-size:22px; letter-spacing:.06em; text-transform:uppercase; }}
.stat .sync {{ font-size:16px; font-weight:600; opacity:.8; border-top:1px solid rgba(14,26,20,.25); padding-top:6px; margin-top:4px; }}
.list {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:24px 26px 14px; display:flex; flex-direction:column; gap:10px; }}
.list h2 {{ font-family:var(--head); font-size:42px; margin:0; text-transform:uppercase; color:var(--go); line-height:1; }}
.list .sub {{ color:var(--muted); font-size:18px; }}
.hdr, li {{ display:grid; grid-template-columns:300px minmax(0,1fr) 140px 200px; gap:16px; align-items:center; }}
.hdr {{ font-size:15px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); border-bottom:1px solid var(--line); padding-bottom:6px; margin-top:6px; }}
.hdr span:nth-child(n+3), .gain, .now {{ text-align:right; }}
ul {{ list-style:none; margin:0; padding:0; }}
li {{ padding:14px 0; border-bottom:1px solid var(--line); font-variant-numeric:tabular-nums; }}
li:last-child {{ border-bottom:0; }}
.nm {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:700; font-size:30px; line-height:1.15; }}
.act {{ display:flex; flex-wrap:wrap; gap:8px; }}
.tag {{ font-size:16px; font-weight:700; letter-spacing:.04em; text-transform:uppercase; border-radius:999px; padding:4px 12px; white-space:nowrap; }}
.tag.vs {{ background:rgba(76,195,138,.16); color:var(--go); }}
.tag.hero {{ background:rgba(167,123,224,.18); color:#c3a2ef; }}
.gain {{ color:var(--go); font-weight:700; font-size:30px; }}
.now {{ color:var(--muted); font-size:20px; display:flex; flex-direction:column; align-items:flex-end; gap:4px; }}
.hit, .togo {{ font-size:15px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; border-radius:999px; padding:2px 10px; }}
.hit {{ background:var(--go); color:#0e1a14; }} .togo {{ border:1px solid var(--vs); color:var(--vs); }}
li.none {{ display:block; color:var(--muted); }}
.sign {{ text-align:center; display:flex; flex-direction:column; gap:6px; padding-top:6px; }}
.sign .t {{ font-family:var(--head); font-weight:700; font-size:46px; text-transform:uppercase; line-height:1; }}
.sign .t span {{ color:var(--go); }}
.sign .f {{ color:var(--muted); font-size:22px; }}
</style></head><body><div class="page">
<header>
  <div>
    <div class="eyebrow">Reborn in Strength · {day.strftime('%A %-d %b')} · VS day</div>
    <h1>Keep <span>going</span></h1>
    <p class="lede"><b>{len(rows)} commanders</b> are online and pushing right now. This is what it takes. Don't stop.</p>
  </div>
  <div class="stat"><span class="big">+{short(total)}</span><span class="lbl">VS pushed since {since_s}</span><span class="sync">Data from {sync_s} server time</span></div>
</header>
<section class="list">
  <h2>Active right now</h2>
  <div class="sub">Seen in uploads since {since_s} server time: VS points gained or heroes upgraded.</div>
  <div class="hdr"><span>Commander</span><span>Activity</span><span>VS gained</span><span>VS today</span></div>
  <ul>{body}</ul>
</section>
<div class="sign"><div class="t">Thank you from the <span>whole team</span></div><div class="f">Every point you push lifts all of us. Keep it up to reset.</div></div>
</div></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Keep-going graphic for recent VS pushers")
    ap.add_argument("--minutes", type=int, default=75, help="Look back this far across uploads")
    ap.add_argument("--out", type=Path, default=Path("reports/out"))
    args = ap.parse_args()
    client = LastWarFarmClient()
    vs_min = int(client.get_alliance()["data"]["settings"]["duelThreshold"])
    day, synced, scores, path = snapshot(client, args.out)
    since, before = baseline(path.parent, synced, args.minutes)
    heroes = hero_activity(client, since)
    rows = []
    for name, today in scores.items():
        gain = max(0, today - before[name]) if name in before else 0
        if gain or name in heroes:
            rows.append((name, gain, today, heroes.get(name)))
    rows.sort(key=lambda r: (-r[1], -(r[3].timestamp() if r[3] else 0)))
    html_path = args.out / f"shoutout_{day}.html"
    html_path.write_text(render(day, since, synced, rows, vs_min), encoding="utf-8")
    print(f"{html_path}  active since {(since - SERVER_OFFSET):%H:%M}: {len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
