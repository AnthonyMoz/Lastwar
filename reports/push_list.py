"""Make a "push now" graphic of everyone under today's targets.

Usage: python reports/push_list.py [--out reports/out]

Targets (from the alliance settings on lastwar.farm):
  VS        today's score under the daily VS minimum
  Donations this week's total under 5,000 x days so far (Mon = 1 ... Sun = 7)
All active members are included. Writes push_<date>.html; render it to PNG
with reports/render.js.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lastwar_farm import LastWarFarmClient  # noqa: E402


# Server time is UTC-2; the daily reset is 00:00 server time.
SERVER_OFFSET = dt.timedelta(hours=2)


def game_day(now: dt.datetime) -> dt.date:
    """In-game day: resets at 00:00 server time (02:00 UTC)."""
    return (now - SERVER_OFFSET).date()


def short(n: int, places: int = 1) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.{places}f}M"
    if n >= 100_000:
        return f"{n / 1_000:.0f}K"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K".replace(".0K", "K")
    return f"{n:,}"


def build(client: LastWarFarmClient, now: dt.datetime):
    s = client.get_alliance()["data"]["settings"]
    vs_min, don_day = int(s["duelThreshold"]), int(s["donationDaily"])
    day = game_day(now)
    week_start = day - dt.timedelta(days=(day.weekday() if s["weekStartDay"] == 1
                                          else (day.weekday() + 1) % 7))
    days_in = (day - week_start).days + 1
    don_target = don_day * days_in
    members = {m["id"]: m for m in client.list_members()["data"] if m["status"] == "ACTIVE"}
    vs = {d["memberId"]: int(d["score"]) for d in client.export_duels()["data"]
          if d["scoredOn"] == day.isoformat()}
    don = {d["memberId"]: int(d["total"]) for d in client.export_donations()["data"]
           if d["weekStart"] == week_start.isoformat()}
    vs_rows = sorted(
        [(m["name"], vs.get(i, 0)) for i, m in members.items() if vs.get(i, 0) < vs_min],
        key=lambda r: r[1])
    don_rows = sorted(
        [(m["name"], don.get(i, 0)) for i, m in members.items() if don.get(i, 0) < don_target],
        key=lambda r: r[1])
    # Duels carry no timestamp; the latest power snapshot marks the last phone sync.
    synced = max(dt.datetime.fromisoformat(p["recordedAt"].replace("Z", "+00:00"))
                 for p in client.export_power()["data"])
    reset = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(2), dt.timezone.utc)
    return dict(day=day, vs_min=vs_min, don_target=don_target, days_in=days_in,
                vs_rows=vs_rows, don_rows=don_rows, members=len(members),
                now=now, synced=synced, left=reset - now, has_vs=bool(vs))


def render(d) -> str:
    """Everyone under today's VS minimum, with a progress bar to the target."""
    e = html.escape
    hrs, mins = divmod(int(d["left"].total_seconds()) // 60, 60)
    vs_min, don_target = d["vs_min"], d["don_target"]

    vs_items = []
    for name, val in d["vs_rows"]:
        pct = max(1.5, min(100.0, 100 * val / vs_min))
        vs_items.append(
            f'<li><span class="nm">{e(name)}</span>'
            f'<span class="track"><span class="fill" style="width:{pct:.1f}%"></span></span>'
            f'<span class="v">{short(val, 2)}</span>'
            f'<span class="need">+{short(vs_min - val)}</span></li>')
    vs_html = "\n".join(vs_items) or '<li class="none">Everyone has hit the VS minimum today.</li>'

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Push Now</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Inter:wght@400;500;600&display=swap">
<style>
:root {{ --bg:#11151b; --panel:#1a2029; --line:#2a3340; --fg:#e9edf2; --muted:#9aa6b4;
  --vs:#e3a63b; --don:#4bb3a8; --bad:#e2675c; --track:#2a3340;
  --head:"Barlow Condensed","Arial Narrow",sans-serif; --body:"Inter","Segoe UI",Arial,sans-serif; }}
* {{ box-sizing:border-box; }} html,body {{ margin:0; background:var(--bg); }}
body {{ width:1080px; color:var(--fg); font-family:var(--body); font-size:22px; line-height:1.35; }}
.page {{ padding:52px 56px 44px; display:flex; flex-direction:column; gap:28px; }}
.eyebrow {{ font-family:var(--head); font-weight:600; letter-spacing:.14em; text-transform:uppercase; color:var(--vs); font-size:24px; }}
h1 {{ font-family:var(--head); font-weight:700; font-size:92px; line-height:.92; margin:6px 0 14px; text-transform:uppercase; }}
h1 span {{ color:var(--vs); }}
.lede {{ margin:0; color:var(--muted); font-size:24px; max-width:920px; }} .lede b {{ color:var(--fg); font-weight:600; }}
header {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:24px; align-items:start; }}
.clock {{ background:var(--vs); color:#11151b; border-radius:10px; padding:16px 22px; text-align:right; display:flex; flex-direction:column; gap:4px; min-width:250px; }}
.clock .big {{ font-family:var(--head); font-weight:700; font-size:54px; line-height:.95; }}
.clock .lbl {{ font-family:var(--head); font-weight:700; font-size:22px; letter-spacing:.06em; text-transform:uppercase; }}
.clock .sync {{ font-size:16px; font-weight:600; opacity:.8; border-top:1px solid rgba(17,21,27,.25); padding-top:6px; margin-top:4px; }}
.vs {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:24px 26px 14px; display:flex; flex-direction:column; gap:10px; }}
.vs h2 {{ font-family:var(--head); font-size:42px; margin:0; text-transform:uppercase; color:var(--vs); line-height:1; }}
.vs .sub {{ color:var(--muted); font-size:18px; }}
.hdr, .vs li {{ display:grid; grid-template-columns:360px minmax(0,1fr) 120px 120px; gap:16px; align-items:center; }}
.hdr {{ font-size:15px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); border-bottom:1px solid var(--line); padding-bottom:6px; margin-top:6px; }}
.hdr span:nth-child(n+3), .v, .need {{ text-align:right; }}
ul {{ list-style:none; margin:0; padding:0; }}
.vs li {{ padding:14px 0; border-bottom:1px solid var(--line); font-variant-numeric:tabular-nums; }}
.vs li:last-child {{ border-bottom:0; }}
.nm {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:700; font-size:30px; line-height:1.15; }}
.track {{ height:16px; background:var(--track); border-radius:6px; overflow:hidden; position:relative; }}
.fill {{ display:block; height:100%; background:var(--vs); border-radius:6px; }}
.v {{ color:var(--muted); font-size:28px; font-weight:500; }} .need {{ color:var(--bad); font-weight:700; font-size:30px; }}
.vs li.none {{ display:block; color:var(--muted); }}
.msg {{ border-left:6px solid var(--bad); background:var(--panel); border-radius:0 10px 10px 0; padding:20px 24px; display:flex; flex-direction:column; gap:6px; }}
.msg .t {{ font-family:var(--head); font-weight:700; font-size:34px; text-transform:uppercase; letter-spacing:.02em; line-height:1.05; }}
.msg p {{ margin:0; color:var(--muted); }} .msg p b {{ color:var(--fg); }}
.don {{ display:flex; flex-direction:column; gap:12px; }}
.don h3 {{ font-family:var(--head); font-size:28px; margin:0; text-transform:uppercase; color:var(--don); letter-spacing:.03em; }}
.don .sub {{ color:var(--muted); font-size:17px; margin-top:-6px; }}
.chips {{ display:flex; flex-wrap:wrap; gap:8px; }}
.chip {{ font-size:17px; border:1px solid var(--line); border-radius:999px; padding:4px 12px; color:var(--fg); }}
.chip b {{ color:var(--don); font-weight:600; }}
</style></head><body><div class="page">
<header>
  <div class="lead">
  <div class="eyebrow">Reborn in Strength · {d['day'].strftime('%A %-d %b')} · VS day</div>
  <h1>Push <span>now</span></h1>
  <p class="lede"><b>{len(d['vs_rows'])} commanders</b> are still under today's <b>{short(vs_min)}</b> VS minimum. We need to push. Get it done before reset.</p>
</div>
  <div class="clock"><span class="big">{hrs}h {mins:02d}m</span><span class="lbl">to reset · 00:00</span><span class="sync">Data from {(d['synced'] - SERVER_OFFSET).strftime('%H:%M')} server time</span></div>
</header>
<section class="vs">
  <h2>Under {short(vs_min)} today</h2>
  <div class="sub">Bar shows progress to {short(vs_min)}. Needs = how much more to hit it.</div>
  <div class="hdr"><span>Commander</span><span>Progress</span><span>Today</span><span>Needs</span></div>
  <ul>{vs_html}</ul>
</section>
</div></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Push-now graphic for today's targets")
    ap.add_argument("--out", type=Path, default=Path("reports/out"))
    args = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    d = build(LastWarFarmClient(), now)
    if not d["has_vs"]:
        print(f"No VS scores for {d['day']} yet (not a VS day, or not synced).", file=sys.stderr)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"push_{d['day']}.html"
    path.write_text(render(d), encoding="utf-8")
    print(f"{path}  VS under: {len(d['vs_rows'])}  donations under: {len(d['don_rows'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
