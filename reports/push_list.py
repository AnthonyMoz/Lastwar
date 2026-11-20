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


def game_day(now: dt.datetime) -> dt.date:
    """In-game day: resets at 02:00 UTC."""
    return (now - dt.timedelta(hours=2)).date()


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
    reset = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(2), dt.timezone.utc)
    return dict(day=day, vs_min=vs_min, don_target=don_target, days_in=days_in,
                vs_rows=vs_rows, don_rows=don_rows, members=len(members),
                now=now, left=reset - now, has_vs=bool(vs))


def render(d) -> str:
    both = {n for n, _ in d["vs_rows"]} & {n for n, _ in d["don_rows"]}
    e = html.escape
    hrs, mins = divmod(int(d["left"].total_seconds()) // 60, 60)

    def rows(items, target, places=1):
        out = []
        for name, val in items:
            mark = '<i class="both" title="Under both targets"></i>' if name in both else ""
            out.append(f'<li><span class="nm">{mark}{e(name)}</span>'
                       f'<span class="v">{short(val, places)}</span>'
                       f'<span class="need">+{short(target - val)}</span></li>')
        return "\n".join(out) or '<li class="none">Everyone has hit it. Nice work.</li>'

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Push Now</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Inter:wght@400;500;600&display=swap">
<style>
:root {{ --bg:#11151b; --panel:#1a2029; --line:#2a3340; --fg:#e9edf2; --muted:#9aa6b4;
  --vs:#e3a63b; --don:#4bb3a8; --bad:#e2675c;
  --head:"Barlow Condensed","Arial Narrow",sans-serif; --body:"Inter","Segoe UI",Arial,sans-serif; }}
* {{ box-sizing:border-box; }} html,body {{ margin:0; background:var(--bg); }}
body {{ width:1080px; color:var(--fg); font-family:var(--body); font-size:22px; line-height:1.35; }}
.page {{ padding:52px 56px 44px; display:flex; flex-direction:column; gap:28px; }}
.eyebrow {{ font-family:var(--head); font-weight:600; letter-spacing:.14em; text-transform:uppercase; color:var(--bad); font-size:24px; }}
h1 {{ font-family:var(--head); font-weight:700; font-size:96px; line-height:.92; margin:6px 0 12px; text-transform:uppercase; }}
.lede {{ margin:0; color:var(--muted); font-size:24px; }} .lede b {{ color:var(--fg); font-weight:600; }}
.clock {{ display:inline-block; margin-top:14px; background:var(--bad); color:#11151b; font-family:var(--head); font-weight:700;
  font-size:30px; padding:6px 16px; border-radius:6px; letter-spacing:.03em; text-transform:uppercase; }}
.cols {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; align-items:start; }}
.col {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:22px 22px 16px; display:flex; flex-direction:column; gap:12px; min-width:0; }}
.col h2 {{ font-family:var(--head); font-size:36px; margin:0; text-transform:uppercase; letter-spacing:.02em; line-height:1; }}
.col.vs h2 {{ color:var(--vs); }} .col.don h2 {{ color:var(--don); }}
.col .sub {{ color:var(--muted); font-size:18px; margin-top:-4px; }}
.hdr, li {{ display:grid; grid-template-columns:minmax(0,1fr) 84px 90px; gap:10px; align-items:center; }}
.hdr {{ font-size:15px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); border-bottom:1px solid var(--line); padding-bottom:6px; }}
.hdr span:not(:first-child), .v, .need {{ text-align:right; }}
ul {{ list-style:none; margin:0; padding:0; display:flex; flex-direction:column; }}
li {{ padding:7px 0; border-bottom:1px solid var(--line); font-size:21px; font-variant-numeric:tabular-nums; }}
li:last-child {{ border-bottom:0; }}
.nm {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:500; display:flex; align-items:center; gap:8px; }}
.v {{ color:var(--muted); }} .need {{ color:var(--bad); font-weight:600; }}
.both {{ flex:none; width:12px; height:12px; border-radius:50%; background:var(--bad); display:inline-block; }}
li.none {{ display:block; color:var(--muted); }}
.key {{ display:flex; flex-wrap:wrap; gap:22px; color:var(--muted); font-size:18px; align-items:center; }}
.key span {{ display:inline-flex; gap:8px; align-items:center; }}
.foot {{ color:var(--muted); font-size:17px; border-top:1px solid var(--line); padding-top:14px; display:flex; justify-content:space-between; gap:20px; }}
</style></head><body><div class="page">
<header>
  <div class="eyebrow">Reborn in Strength · {d['day'].strftime('%A %-d %b')}</div>
  <h1>Push now</h1>
  <p class="lede"><b>{len(d['vs_rows'])}</b> commanders are under today's VS minimum and <b>{len(d['don_rows'])}</b> are behind on donations. Get it done before reset.</p>
  <div class="clock">{hrs}h {mins:02d}m to reset · 02:00 UTC</div>
</header>
<div class="cols">
  <section class="col vs"><h2>VS under {short(d['vs_min'])}</h2><div class="sub">Today's score so far</div>
    <div class="hdr"><span>Commander</span><span>Today</span><span>Needs</span></div>
    <ul>{rows(d['vs_rows'], d['vs_min'], 2)}</ul></section>
  <section class="col don"><h2>Donations under {short(d['don_target'])}</h2><div class="sub">This week so far ({d['days_in']} days × 5K)</div>
    <div class="hdr"><span>Commander</span><span>Week</span><span>Needs</span></div>
    <ul>{rows(d['don_rows'], d['don_target'])}</ul></section>
</div>
<div class="key"><span><i class="both"></i>Under both targets</span><span>Needs = how much more to hit the target</span></div>
<div class="foot"><span>From lastwar.farm, as of {d['now'].strftime('%H:%M UTC')}. Already pushed since then? You're clear.</span><span>Check your rank: kingbob.lastwar.farm/events/kick-rank</span></div>
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
