"""Work out each member's kick rank and optionally load it into lastwar.farm.

Usage:
  python reports/kick_rank.py                        # show the ranking only
  python reports/kick_rank.py --event-id <id>        # also preview the upload
  python reports/kick_rank.py --event-id <id> --run-id <run> --commit
  python reports/kick_rank.py --excuse "Some Name" --excuse <memberId>

Kick score is 0-100, higher means more at risk, over the last 4 full weeks:
  55%  share of VS days under the alliance's daily VS minimum
  35%  how far average weekly donations fall short of the weekly target
  10%  power fell over the period
Rank 1 is the member most at risk.

Not ranked:
  - members who joined in the last 14 days (grace period)
  - members missing VS rows on more than 25% of their VS days. lastwar.farm
    does not record a leave and rejoin, but an idle member still gets a VS
    row (often 0), so missing rows usually mean they were out of the alliance.
  - anyone passed with --excuse (name or member id), e.g. known absences
Storms are not scored, because being picked is an officer decision.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lastwar_farm import LastWarFarmClient  # noqa: E402

WEEKS = 4
GRACE_DAYS = 14
MAX_MISSING_SHARE = 0.25
WEIGHTS = {"vs": 0.55, "donations": 0.35, "power": 0.10}
RESET = "T02:00:00"


def window(today: dt.date, week_start_day: int):
    py_start = 0 if week_start_day == 1 else 6
    this_week = today - dt.timedelta(days=(today.weekday() - py_start) % 7)
    weeks = [this_week - dt.timedelta(days=7 * i) for i in range(WEEKS, 0, -1)]
    return weeks, this_week


def last_before(series, boundary):
    value = None
    for at, v in series:
        if at >= boundary:
            break
        value = v
    return value


def compute(client: LastWarFarmClient, today: dt.date, excuse: set[str]):
    alliance = client.get_alliance()["data"]
    s = alliance["settings"]
    vs_min = int(s["duelThreshold"])
    don_target = int(s["donationDaily"]) * 7
    weeks, end = window(today, s["weekStartDay"])
    start_iso, end_iso = weeks[0].isoformat(), end.isoformat()
    grace_from = (today - dt.timedelta(days=GRACE_DAYS)).isoformat()

    members = [m for m in client.list_members()["data"] if m["status"] == "ACTIVE"]
    duels = [d for d in client.export_duels()["data"] if start_iso <= d["scoredOn"] < end_iso]
    vs_days = sorted({d["scoredOn"] for d in duels})
    vs = defaultdict(dict)
    for d in duels:
        vs[d["memberId"]][d["scoredOn"]] = int(d["score"])
    don = {(d["memberId"], d["weekStart"]): int(d["total"])
           for d in client.export_donations()["data"]}
    power = defaultdict(list)
    for p in client.export_power()["data"]:
        power[p["memberId"]].append((p["recordedAt"], int(p["power"])))
    for v in power.values():
        v.sort()

    ranked, skipped = [], []
    for m in members:
        mid, name, joined = m["id"], m["name"], m["joinedAt"][:10]
        if mid in excuse or name in excuse:
            skipped.append((name, "excused"))
            continue
        if joined >= grace_from:
            skipped.append((name, f"joined {joined}, in grace period"))
            continue
        days = [d for d in vs_days if d >= joined]
        scores = [vs[mid].get(d) for d in days]
        missing = sum(1 for x in scores if x is None)
        if not days or missing / len(days) > MAX_MISSING_SHARE:
            skipped.append((name, f"no VS record on {missing} of {len(days)} days, check in game"))
            continue
        under = sum(1 for x in scores if x is None or x < vs_min)
        weeks_in = [w for w in weeks if (w + dt.timedelta(days=7)).isoformat() > joined]
        don_avg = sum(don.get((mid, w.isoformat()), 0) for w in weeks_in) / len(weeks_in)
        p0 = last_before(power[mid], start_iso + RESET)
        p1 = last_before(power[mid], end_iso + RESET)
        power_fell = p0 is not None and p1 is not None and p1 < p0
        score = 100 * (WEIGHTS["vs"] * under / len(days)
                       + WEIGHTS["donations"] * max(0.0, 1 - don_avg / don_target)
                       + WEIGHTS["power"] * power_fell)
        ranked.append({
            "memberId": mid, "name": name, "role": m["role"],
            "score": round(score, 1), "vsUnder": under, "vsDays": len(days),
            "donationsAvg": round(don_avg), "powerFell": power_fell,
        })
    ranked.sort(key=lambda r: (-r["score"], r["name"]))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    info = {"from": start_iso, "to": (end - dt.timedelta(days=1)).isoformat(),
            "vsMin": vs_min, "donationTarget": don_target}
    return ranked, skipped, info


def main() -> int:
    ap = argparse.ArgumentParser(description="Kick rank for the alliance")
    ap.add_argument("--event-id", help="Custom event to load the rank into")
    ap.add_argument("--rank-metric", default="rank", help="Metric name for the rank")
    ap.add_argument("--score-metric", default="score", help="Metric name for the score")
    ap.add_argument("--run-id", help="Existing run to load into (needed for Runs events)")
    ap.add_argument("--commit", action="store_true", help="Actually upload (default: preview)")
    ap.add_argument("--excuse", action="append", default=[], help="Name or member id to skip")
    ap.add_argument("--top", type=int, default=10, help="How many to print")
    args = ap.parse_args()

    client = LastWarFarmClient()
    today = dt.datetime.now(dt.timezone.utc).date()
    ranked, skipped, info = compute(client, today, set(args.excuse))

    print(f"Kick rank for {info['from']} to {info['to']} "
          f"(VS minimum {info['vsMin']:,}, donation target {info['donationTarget']:,}/week)")
    for r in ranked[: args.top]:
        print(f"{r['rank']:>3}. {r['name']:<22} {r['role']}  score {r['score']:>5}  "
              f"VS under {r['vsUnder']}/{r['vsDays']}  donations {r['donationsAvg']:>7,}/wk"
              f"{'  power fell' if r['powerFell'] else ''}")
    print(f"Ranked {len(ranked)}; not ranked {len(skipped)}:")
    for name, why in skipped:
        print(f"   - {name}: {why}")

    if not args.event_id:
        return 0
    event = next((e for e in client.list_custom_events()["data"] if e["id"] == args.event_id), None)
    if event is None:
        print(f"No custom event with id {args.event_id}", file=sys.stderr)
        return 1
    metrics = {m["name"].lower(): m["id"] for m in event["metrics"]}
    uploads = [(args.rank_metric, "rank"), (args.score_metric, "score")]
    missing = [name for name, _ in uploads if name.lower() not in metrics]
    if missing:
        print(f"Event '{event['name']}' has no metric named {missing}. "
              f"It has: {[m['name'] for m in event['metrics']]}", file=sys.stderr)
        return 1
    if event["eventType"] == "RUNS" and not args.run_id:
        print(f"'{event['name']}' is a Runs event: create a run for today in lastwar.farm, "
              "then pass its id with --run-id.", file=sys.stderr)
        return 1
    recorded_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    for metric_name, field in uploads:
        entries = [{"memberId": r["memberId"], "value": r[field]} for r in ranked]
        if not args.commit:
            print(f"Preview: would upload {len(entries)} '{metric_name}' values to "
                  f"'{event['name']}' at {recorded_at}. Add --commit to upload.")
            continue
        result = client.import_custom_event_entries(
            event["id"], entries, recorded_at=recorded_at,
            metric_id=metrics[metric_name.lower()], run_id=args.run_id)
        data = result.get("data", result) if isinstance(result, dict) else result
        print(f"Uploaded '{metric_name}': {data}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
