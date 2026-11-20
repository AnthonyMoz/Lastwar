"""Make a "keep going" graphic for commanders pushing VS recently.

Usage: python reports/shoutout.py [--minutes 60] [--out reports/out]

lastwar.farm VS scores have no timestamps, so every run saves a snapshot of
everyone's VS score for the day (reports/out/vs_snapshots/<day>/<HHMM>.json,
keyed by the last phone sync time). The graphic compares the latest data with
the snapshot closest to --minutes ago (at least 15 minutes old). Writes
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
    """Snapshot closest to `minutes` before `synced`, at least 15 minutes older."""
    best = None
    for f in folder.glob("*.json"):
        snap = json.loads(f.read_text(encoding="utf-8"))
        t = dt.datetime.fromisoformat(snap["synced"])
        age = (synced - t).total_seconds() / 60
        if age < 15:
            continue
        score = abs(age - minutes)
        if best is None or score < best[0]:
            best = (score, t, snap["scores"])
    return (best[1], best[2]) if best else (None, None)


def render(day, since, synced, rows, vs_min) -> str:
    e = html.escape
    since_s = (since - SERVER_OFFSET).strftime("%H:%M")
    sync_s = (synced - SERVER_OFFSET).strftime("%H:%M")
    top = max((a - b for _, b, a in rows), default=1)
    items = []
    for name, before, after in rows:
        gain = after - before
        hit = after >= vs_min
        badge = '<span class="hit">Target hit</span>' if hit else f'<span class="togo">{short(vs_min - after)} to go</span>'
        items.append(
            f'<li><span class="nm">{e(name)}</span>'
            f'<span class="track"><span class="fill" style="width:{max(3, 100 * gain / top):.1f}%"></span></span>'
            f'<span class="gain">+{short(gain)}</span>'
            f'<span class="now">{short(after, 2)} {badge}</span></li>')
    body = "\n".join(items) or '<li class="none">No new VS points since then yet. Be the first.</li>'
    total = sum(a - b for _, b, a in rows)
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
.hdr, li {{ display:grid; grid-template-columns:340px minmax(0,1fr) 130px 230px; gap:16px; align-items:center; }}
.hdr {{ font-size:15px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); border-bottom:1px solid var(--line); padding-bottom:6px; margin-top:6px; }}
.hdr span:nth-child(n+3), .gain, .now {{ text-align:right; }}
ul {{ list-style:none; margin:0; padding:0; }}
li {{ padding:14px 0; border-bottom:1px solid var(--line); font-variant-numeric:tabular-nums; }}
li:last-child {{ border-bottom:0; }}
.nm {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:700; font-size:30px; line-height:1.15; }}
.track {{ height:16px; background:var(--track); border-radius:8px; overflow:hidden; }}
.fill {{ display:block; height:100%; background:var(--go); border-radius:8px; }}
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
    <p class="lede"><b>{len(rows)} commanders</b> have pushed since {since_s}. This is what it takes. Don't stop now.</p>
  </div>
  <div class="stat"><span class="big">+{short(total)}</span><span class="lbl">VS since {since_s}</span><span class="sync">Data from {sync_s} server time</span></div>
</header>
<section class="list">
  <h2>Pushing since {since_s}</h2>
  <div class="sub">VS points gained since {since_s} server time, biggest first.</div>
  <div class="hdr"><span>Commander</span><span>Gained</span><span>Points</span><span>Today</span></div>
  <ul>{body}</ul>
</section>
<div class="sign"><div class="t">Thank you from the <span>whole team</span></div><div class="f">Every point you push lifts all of us. Keep it up to reset.</div></div>
</div></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Keep-going graphic for recent VS pushers")
    ap.add_argument("--minutes", type=int, default=60, help="Look back this far")
    ap.add_argument("--out", type=Path, default=Path("reports/out"))
    args = ap.parse_args()
    client = LastWarFarmClient()
    vs_min = int(client.get_alliance()["data"]["settings"]["duelThreshold"])
    day, synced, scores, path = snapshot(client, args.out)
    since, before = baseline(path.parent, synced, args.minutes)
    if since is None:
        print(f"Saved snapshot {path}. No earlier snapshot to compare with yet; run again after the next sync.")
        return 0
    rows = sorted(((n, before[n], s) for n, s in scores.items() if n in before and s > before[n]),
                  key=lambda r: -(r[2] - r[1]))
    html_path = args.out / f"shoutout_{day}.html"
    html_path.write_text(render(day, since, synced, rows, vs_min), encoding="utf-8")
    print(f"{html_path}  pushers since {(since - SERVER_OFFSET):%H:%M}: {len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
