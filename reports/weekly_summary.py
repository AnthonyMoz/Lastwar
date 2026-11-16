"""Build last week's alliance summary from the lastwar.farm API.

Usage: python reports/weekly_summary.py [--week-start YYYY-MM-DD] [--out DIR]

Writes four JSON files, each {"rows": [...], "meta": [...]}:
  settings.json  one row: alliance name, week range, thresholds
  members.json   one row per active member: power, kills, VS, donations
  vs_daily.json  one row per VS day: alliance total vs the week before
  storms.json    one row per storm assignment held during the week

Weeks follow the alliance's weekStartDay and the 02:00 UTC in-game reset.
Power and kills changes compare the last snapshot before the week's first
reset with the last snapshot before the next week's first reset.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lastwar_farm import LastWarFarmClient  # noqa: E402

RESET = "T02:00:00"


def last_week_start(today: dt.date, week_start_day: int) -> dt.date:
    """Monday (1) or Sunday (0) that began the most recent full week."""
    py_start = 0 if week_start_day == 1 else 6  # Python: Monday=0, Sunday=6
    this_week = today - dt.timedelta(days=(today.weekday() - py_start) % 7)
    return this_week - dt.timedelta(days=7)


def snapshot_before(series, boundary: str):
    """Last value recorded strictly before an ISO timestamp, or None."""
    value = None
    for recorded_at, v in series:  # sorted ascending
        if recorded_at >= boundary:
            break
        value = v
    return value


def by_member(rows, field):
    out = defaultdict(list)
    for r in rows:
        out[r["memberId"]].append((r["recordedAt"], int(r[field])))
    for v in out.values():
        v.sort()
    return out


def change(series, t0, t1):
    a, b = snapshot_before(series, t0), snapshot_before(series, t1)
    return (a, b, b - a) if a is not None and b is not None else (a, b, None)


def build(client: LastWarFarmClient, week_start: dt.date | None):
    alliance = client.get_alliance()["data"]
    settings = alliance["settings"]
    if week_start is None:
        week_start = last_week_start(dt.datetime.now(dt.timezone.utc).date(),
                                     settings["weekStartDay"])
    prev_start = week_start - dt.timedelta(days=7)
    next_start = week_start + dt.timedelta(days=7)
    iso = lambda d: d.isoformat()  # noqa: E731
    t_prev, t0, t1 = (iso(d) + RESET for d in (prev_start, week_start, next_start))

    members = [m for m in client.list_members()["data"] if m["status"] == "ACTIVE"]
    power = by_member(client.export_power()["data"], "power")
    kills = by_member(client.export_kills()["data"], "kills")
    duels = client.export_duels()["data"]
    donations = client.export_donations()["data"]
    threshold = int(settings["duelThreshold"])

    def in_week(day: str, start: dt.date) -> bool:
        return iso(start) <= day < iso(start + dt.timedelta(days=7))

    vs = defaultdict(lambda: {"cur": [], "prev": []})
    for d in duels:
        if in_week(d["scoredOn"], week_start):
            vs[d["memberId"]]["cur"].append(int(d["score"]))
        elif in_week(d["scoredOn"], prev_start):
            vs[d["memberId"]]["prev"].append(int(d["score"]))
    don = {(d["memberId"], d["weekStart"]): int(d["total"]) for d in donations}

    member_rows = []
    for m in members:
        mid = m["id"]
        p0, p1, dp = change(power.get(mid, []), t0, t1)
        _, _, dp_prev = change(power.get(mid, []), t_prev, t0)
        k0, k1, dk = change(kills.get(mid, []), t0, t1)
        _, _, dk_prev = change(kills.get(mid, []), t_prev, t0)
        cur, prev = vs[mid]["cur"], vs[mid]["prev"]
        member_rows.append({
            "memberId": mid,
            "name": m["name"],
            "role": m["role"],
            "joinedAt": m["joinedAt"],
            "newThisWeek": t0 <= m["joinedAt"] < t1,
            "powerStart": p0,
            "powerEnd": p1,
            "powerChange": dp,
            "powerChangePrevWeek": dp_prev,
            "killsChange": dk,
            "killsChangePrevWeek": dk_prev,
            "vsTotal": sum(cur) if cur else None,
            "vsTotalPrevWeek": sum(prev) if prev else None,
            "vsDaysScored": len(cur),
            "vsDaysBelowThreshold": sum(1 for s in cur if s < threshold),
            "donations": don.get((mid, iso(week_start))),
            "donationsPrevWeek": don.get((mid, iso(prev_start))),
        })

    daily = defaultdict(lambda: {"total": 0, "members": 0, "below": 0})
    for d in duels:
        day = d["scoredOn"]
        if in_week(day, week_start) or in_week(day, prev_start):
            row = daily[day]
            row["total"] += int(d["score"])
            row["members"] += 1
            row["below"] += int(d["score"]) < threshold
    vs_rows = []
    for i in range(7):
        day = week_start + dt.timedelta(days=i)
        before = day - dt.timedelta(days=7)
        cur, prev = daily.get(iso(day)), daily.get(iso(before))
        if not cur and not prev:
            continue
        vs_rows.append({
            "day": iso(day),
            "weekday": day.strftime("%a"),
            "total": cur["total"] if cur else None,
            "membersScored": cur["members"] if cur else 0,
            "membersBelowThreshold": cur["below"] if cur else 0,
            "prevWeekDay": iso(before),
            "prevWeekTotal": prev["total"] if prev else None,
        })

    storm_rows = []
    # The API's from/to filter is not applied server-side, so filter here.
    for ev in client.list_storms()["data"]:
        if not in_week(ev["eventDate"], week_start):
            continue
        detail = client.get_storm_assignments(ev["id"])["data"]
        for a in detail["assignments"]:
            storm_rows.append({
                "eventId": ev["id"],
                "stormType": ev["type"],
                "eventDate": ev["eventDate"],
                "memberId": a["memberId"],
                "name": a["memberName"],
                "team": a["team"],
                "role": a["role"],
                # "attended" is omitted: the API reports false even for members with a score.
                "score": int(a["score"]) if a.get("score") is not None else None,
            })

    settings_row = [{
        "alliance": alliance["name"],
        "slug": alliance["slug"],
        "weekStart": iso(week_start),
        "weekEnd": iso(next_start - dt.timedelta(days=1)),
        "prevWeekStart": iso(prev_start),
        "duelThreshold": threshold,
        "donationDaily": int(settings["donationDaily"]),
        "donationWeeklyTarget": int(settings["donationDaily"]) * 7,
        "activeMembers": len(members),
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }]
    return {"settings": settings_row, "members": member_rows,
            "vs_daily": vs_rows, "storms": storm_rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--week-start", type=dt.date.fromisoformat,
                    help="First day of the week to report (default: last full week)")
    ap.add_argument("--out", type=Path, default=Path("reports/out"))
    args = ap.parse_args()

    data = build(LastWarFarmClient(), args.week_start)
    args.out.mkdir(parents=True, exist_ok=True)
    code = Path(__file__).read_text(encoding="utf-8")
    week = data["settings"][0]
    for name, rows in data.items():
        meta = [
            {"label": "weekly_summary.py", "value": code, "type": "code", "lang": "python"},
            {"label": "Input", "value": "lastwar.farm Public API v1 (alliance key)"},
            {"label": "Week", "value": f"{week['weekStart']} to {week['weekEnd']}"},
            {"label": "Generated", "value": week["generatedAt"]},
        ]
        (args.out / f"{name}.json").write_text(
            json.dumps({"rows": rows, "meta": meta}, ensure_ascii=False), encoding="utf-8")
        print(f"{name}: {len(rows)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
