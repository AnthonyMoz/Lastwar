"""Work out the weekly Train list and make the RI5E graphic and Merv announcement.

Usage:
  python reports/train_list.py --type push --days 6 --word VEGEMITE --gag "..." --example "..."
  python reports/train_list.py --type save                 # Mon-Fri, days over 10M count zero
  python reports/train_list.py --week-start 2026-11-16 --swap "Name A" "Name B"

Ranks active members by VS points for the week (default: the last full week).
Ranks 1-7 conduct Mon-Sun and ranks 8-14 ride VIP Mon-Sun. Writes
train_<week>.html (render with reports/render.js) and train_<week>.txt to
reports/out, and records the week's Merv word in reports/merv_words.txt so a
word is never reused.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lastwar_farm import LastWarFarmClient  # noqa: E402

SERVER_OFFSET = dt.timedelta(hours=2)  # server time is UTC-2; reset is 00:00 server time
SAVE_CAP = 10_000_000                  # save week: a day over this counts as zero
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
CHAR_LIMIT = 490
WORDS_FILE = Path(__file__).resolve().parent / "merv_words.txt"
WORD_IDEAS = ["THONGS", "BROLLY", "ARVO", "BOGAN", "TINNIE", "BARBIE", "SNAG", "DROPBEAR",
              "LAMINGTON", "STUBBY", "CHOOK", "DAGGY", "WOOP WOOP", "TRACKIES", "UTE"]


def rank(client: LastWarFarmClient, monday: dt.date, week_type: str, days: int):
    """Return (rows, left, synced). rows: active members, best first, as dicts."""
    dates = [(monday + dt.timedelta(days=i)).isoformat() for i in range(days)]
    members = {m["id"]: m for m in client.list_members()["data"]}
    week_open = dt.datetime.combine(monday, dt.time(), dt.timezone.utc) + SERVER_OFFSET
    per: dict[str, dict[str, int]] = {}
    for d in client.export_duels()["data"]:
        if d["scoredOn"] in dates:
            per.setdefault(d["memberId"], {})[d["scoredOn"]] = int(d["score"])
    rows, left = [], []
    for mid, scores in per.items():
        m = members.get(mid)
        if not m:
            continue
        pts = [scores.get(day, 0) for day in dates]
        counted = [0 if week_type == "save" and p > SAVE_CAP else p for p in pts]
        joined = dt.datetime.fromisoformat(m["joinedAt"].replace("Z", "+00:00"))
        row = {"name": m["name"], "role": m["role"], "status": m["status"], "points": pts,
               "total": sum(counted), "partial": joined > week_open}
        (rows if m["status"] in ("ACTIVE", "EXCUSED") else left).append(row)
    rows.sort(key=lambda r: -r["total"])
    left.sort(key=lambda r: -r["total"])
    synced = max(dt.datetime.fromisoformat(r["recordedAt"].replace("Z", "+00:00"))
                 for r in client.export_power()["data"])
    return rows, left, synced


def merv_word(week: str, word: str | None) -> str:
    """Return this week's word, refusing one used in another week, and record it."""
    used = {}
    for line in WORDS_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            wk, w = line.split(maxsplit=1)
            used[w.strip().upper()] = wk
    if word is None:
        word = next((w for w, wk in used.items() if wk == week), None) \
            or next(w for w in WORD_IDEAS if w not in used)
    word = word.upper()
    if used.get(word, week) != week:
        raise SystemExit(f"Merv's word {word} was already used ({used[word]}). Pick a new one.")
    if word not in used:
        with WORDS_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{week} {word}\n")
    return word


def announcement(top: list[dict], gag: str, word: str, example: str | None) -> str:
    lines = ["RI5E TRAIN TIME", f"Merv here. {gag}", "", "Conductor / VIP"]
    lines += [f"{DAYS[i]}: {top[i]['name']} / {top[i + 7]['name']}" for i in range(7)]
    lines += ["", f"Merv's word: {word}", "",
              f"Post {word} in the alliance chat. For example: {example or word + ', read it!'}"]
    return "\n".join(lines)


def render(top: list[dict], subtitle: str, banner: str | None) -> str:
    e = html.escape
    rnd = random.Random(5)
    embers = "".join(
        f'<i style="left:{rnd.uniform(0, 100):.1f}%;top:{(1 - rnd.random() ** 2) * 100:.1f}%;'
        f'width:{s}px;height:{s}px;opacity:{rnd.uniform(.25, .8):.2f}"></i>'
        for s in (rnd.choice([3, 4, 5, 6, 8]) for _ in range(90)))
    chevrons = "".join(
        f'<polyline points="-20,{y + 60} 540,{y} 1100,{y + 60}"/>' for y in range(60, 1900, 150))
    cards = "".join(
        f'<div class="card"><div class="day">{DAYS[i].upper()}</div>'
        f'<div class="seat c"><span class="n">#{i + 1} ★</span><span class="nm">{e(top[i]["name"])}</span></div>'
        f'<div class="seat v"><span class="n">#{i + 8}</span><span class="nm">{e(top[i + 7]["name"])}</span></div></div>'
        for i in range(7))
    banner_html = f'<div class="banner">{e(banner)}</div>' if banner else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>RI5E Train Schedule</title>
<style>
:root {{ --gold:#ffb43c; --gold2:#ffe08a; --blue:#7fcbff; --ink:#1c1206;
  --font:"DejaVu Sans","Noto Sans CJK JP","Noto Sans CJK SC","Loma",sans-serif; }}
* {{ box-sizing:border-box; }} html,body {{ margin:0; }} html {{ background:#f28a1e; }}
body {{ width:1080px; position:relative; overflow:hidden; color:#fff; font-family:var(--font); font-weight:700;
  background:linear-gradient(180deg,#070a1c 0%,#131536 30%,#22143c 58%,#3e1a2c 76%,#a04716 92%,#f28a1e 100%); }}
.fx {{ position:absolute; inset:0; pointer-events:none; }}
.fx svg {{ width:100%; height:100%; }} .fx polyline {{ fill:none; stroke:rgba(255,180,60,.09); stroke-width:3; }}
.fx i {{ position:absolute; border-radius:50%; background:#ffc46a; box-shadow:0 0 6px #ff9a2e; }}
.glow {{ position:absolute; left:50%; top:-120px; width:900px; height:560px; transform:translateX(-50%);
  background:radial-gradient(closest-side,rgba(255,150,40,.62),rgba(255,150,40,.18) 60%,transparent); }}
.page {{ position:relative; padding:30px 36px 22px; display:flex; flex-direction:column; align-items:center; }}
.logo {{ font-size:236px; line-height:1; letter-spacing:.02em; margin-top:6px;
  background:linear-gradient(180deg,#ffe9a6 0%,#ffc75a 45%,#ff8a1f 100%); -webkit-background-clip:text; color:transparent;
  filter:drop-shadow(0 0 26px rgba(255,150,40,.75)); }}
.tag {{ font-size:32px; letter-spacing:.42em; color:var(--gold2); margin-top:4px; padding-left:.42em; }}
.rule {{ width:860px; display:flex; align-items:center; gap:22px; margin:26px 0 22px; }}
.rule::before, .rule::after {{ content:""; flex:1; height:3px; background:var(--gold); }}
.rule b {{ width:24px; height:24px; background:var(--gold); transform:rotate(45deg); }}
h1 {{ font-size:62px; margin:0; letter-spacing:.02em; line-height:1.1; }}
.pill {{ margin-top:14px; background:var(--gold); color:var(--ink); border-radius:999px; padding:9px 30px; font-size:26px;
  white-space:nowrap; box-shadow:0 0 22px rgba(255,160,40,.5); }}
.banner {{ margin-top:22px; width:100%; text-align:center; background:linear-gradient(90deg,#ffcf6b,#ffa62b); color:var(--ink);
  border-radius:14px; padding:14px 20px; font-size:28px; }}
.cols {{ width:100%; display:grid; grid-template-columns:264px 414px 1fr; margin:24px 0 10px; font-size:26px; }}
.cols .c {{ grid-column:2; color:var(--gold); }} .cols .v {{ color:var(--blue); padding-left:22px; }}
.cards {{ width:100%; display:flex; flex-direction:column; gap:16px; }}
.card {{ height:124px; display:grid; grid-template-columns:240px 414px 1fr; align-items:center;
  background:rgba(12,12,34,.82); border:2px solid rgba(255,180,60,.45); border-left:12px solid var(--gold);
  border-radius:8px 26px 26px 8px; padding-right:24px; }}
.day {{ margin-left:18px; width:180px; height:86px; background:var(--gold); color:var(--ink); font-size:50px;
  display:flex; align-items:center; justify-content:center; padding-right:14px;
  clip-path:polygon(0 0,88% 0,100% 100%,0 100%); }}
.seat {{ display:flex; flex-direction:column; gap:4px; min-width:0; height:84px; justify-content:center; }}
.seat.v {{ border-left:2px solid rgba(255,180,60,.7); padding-left:22px; }}
.n {{ font-size:24px; }} .c .n {{ color:var(--gold); }} .v .n {{ color:var(--blue); }}
.nm {{ font-size:42px; line-height:1.2; white-space:nowrap; display:block; overflow:hidden; padding-right:8px; }}
footer {{ margin-top:52px; text-align:center; color:var(--ink); font-size:27px; }}
footer span {{ display:block; font-weight:400; font-size:22px; margin-top:4px; }}
</style></head><body>
<div class="fx"><svg viewBox="0 0 1080 1900" preserveAspectRatio="none">{chevrons}</svg>{embers}</div><div class="glow"></div>
<div class="page">
  <div class="logo">RI5E</div>
  <div class="tag">REBORN IN STRENGTH</div>
  <div class="rule"><b></b></div>
  <h1>TRAIN SCHEDULE</h1>
  <div class="pill">{e(subtitle)}</div>
  {banner_html}
  <div class="cols"><span class="c">CONDUCTOR</span><span class="v">VIP</span></div>
  <div class="cards">{cards}</div>
  <footer>Shield up, rise together, and don't be a Merv.<span>- Cozmos</span></footer>
</div>
<script>
for (const el of document.querySelectorAll('.nm')) {{
  let size = 42;
  while (el.scrollWidth > el.clientWidth && size > 20) el.style.fontSize = --size + 'px';
}}
</script></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Weekly Train list, graphic and Merv announcement")
    ap.add_argument("--week-start", type=dt.date.fromisoformat, help="Monday of the scored week (default: last full week)")
    ap.add_argument("--type", choices=["push", "save"], required=True)
    ap.add_argument("--days", type=int, choices=[5, 6], help="Days counted from Monday (default: push 6, save 5)")
    ap.add_argument("--exclude", action="append", default=[], help="Leave this name off the list (repeatable)")
    ap.add_argument("--swap", nargs=2, action="append", default=[], metavar=("A", "B"), help="Swap two names' slots")
    ap.add_argument("--gag", default="Never on the list, always at the servo.", help="Merv's one-liner")
    ap.add_argument("--word", help="Merv's word (default: next unused idea)")
    ap.add_argument("--example", help="Example of what members could post with the word")
    ap.add_argument("--banner", help="Optional gold banner text")
    ap.add_argument("--out", type=Path, default=Path("reports/out"))
    args = ap.parse_args()

    today = (dt.datetime.now(dt.timezone.utc) - SERVER_OFFSET).date()
    monday = args.week_start or today - dt.timedelta(days=today.weekday() + 7)
    days = args.days or (6 if args.type == "push" else 5)
    rows, left, synced = rank(LastWarFarmClient(), monday, args.type, days)
    rows = [r for r in rows if r["name"] not in args.exclude]
    if len(rows) < 14:
        raise SystemExit(f"Only {len(rows)} members have scores for the week of {monday}.")

    week_end = dt.datetime.combine(monday + dt.timedelta(days=days), dt.time(), dt.timezone.utc) + SERVER_OFFSET
    print(f"Week {monday} to {monday + dt.timedelta(days=days - 1)}, {args.type}, {days} days. "
          f"Last game sync {(synced - SERVER_OFFSET):%a %d %b %H:%M} server time.")
    if synced < week_end:
        print("WARNING: the last sync is before the final counted day closed, so totals may still change.")
    for i, r in enumerate(rows[:18], 1):
        flags = [f for f, on in (("EXCUSED", r["status"] == "EXCUSED"), ("PARTIAL WEEK", r["partial"])) if on]
        print(f"{'--- cut ---' + chr(10) if i == 15 else ''}{i:>2} {r['name']:<20} {r['role']} {r['total']:>13,}"
              f"  {' '.join(flags)}")
    print(f"Cut: #14 beats #15 by {rows[13]['total'] - rows[14]['total']:,}.")
    for i in range(14):
        gap = rows[i]["total"] - rows[i + 1]["total"]
        if gap < 500_000:
            print(f"Near-tie: #{i + 1} {rows[i]['name']} over #{i + 2} {rows[i + 1]['name']} by {gap:,}"
                  + (" (tie, order is arbitrary)" if gap == 0 else ""))
    for r in left:
        if r["total"] >= rows[13]["total"]:
            print(f"Left the alliance, skipped: {r['name']} ({r['total']:,})")

    top = rows[:14]
    names = [r["name"] for r in top]
    for a, b in args.swap:
        i, j = names.index(a), names.index(b)
        top[i], top[j], names[i], names[j] = top[j], top[i], names[j], names[i]

    span = "MON-SAT" if days == 6 else "MON-FRI"
    subtitle = f"{args.type.upper()} WEEK  •  TOP 14  •  {span} {'TOTALS' if args.type == 'push' else 'CAPPED'}"
    text = announcement(top, args.gag, merv_word(monday.isoformat(), args.word), args.example)
    args.out.mkdir(parents=True, exist_ok=True)
    html_path = args.out / f"train_{monday}.html"
    html_path.write_text(render(top, subtitle, args.banner), encoding="utf-8")
    (args.out / f"train_{monday}.txt").write_text(text + "\n", encoding="utf-8")
    print(f"\n{text}\n\n{len(text)} characters (limit about {CHAR_LIMIT})"
          + ("  TOO LONG" if len(text) > CHAR_LIMIT else ""))
    print(html_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
