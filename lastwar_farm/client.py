"""HTTP client for the lastwar.farm (FarmOps) Public API v1.

Spec: https://lastwar.farm/api/v1/openapi.json (vendored in ``openapi/``).

Keys are bound to one tenant: an *alliance* key works only on
``/api/v1/alliance/*`` and a *server* key only on ``/api/v1/server/*``.
Limits are 60 requests/minute and 5,000/day per key.

Big counters (power, kills, THP, VS score, donations) come back as JSON
strings because they can exceed 2**53; convert with ``int(value)``.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union

from . import __version__
from .errors import ApiError, ConfigError, RateLimitedError

DEFAULT_BASE_URL = "https://www.lastwar.farm"  # host used by /docs/api
API_KEY_ENV = "LASTWAR_FARM_API_KEY"
#: Also accepted, in order, if API_KEY_ENV is unset (e.g. the cloud secret name).
FALLBACK_KEY_ENVS = ("API_Key",)
BASE_URL_ENV = "LASTWAR_FARM_BASE_URL"

Entries = Iterable[Mapping[str, Any]]


def load_dotenv(path: Union[str, Path] = ".env") -> None:
    """Load KEY=VALUE lines from a .env file into os.environ (no overwrite)."""
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


class LastWarFarmClient:
    """Thin wrapper over every endpoint in the FarmOps Public API v1.

    >>> client = LastWarFarmClient()            # reads LASTWAR_FARM_API_KEY
    >>> client.get_alliance()
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        dotenv_path: Optional[Union[str, Path]] = ".env",
    ) -> None:
        if dotenv_path:
            load_dotenv(dotenv_path)
        self.api_key = api_key or next(
            (os.environ[n] for n in (API_KEY_ENV, *FALLBACK_KEY_ENVS) if os.environ.get(n)),
            None,
        )
        if not self.api_key:
            raise ConfigError(
                f"No API key. Pass api_key=... or set {API_KEY_ENV} "
                "(see .env.example)."
            )
        self.base_url = (
            base_url or os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL
        ).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        #: Rate-limit headers from the most recent response.
        self.rate_limit: Dict[str, Optional[str]] = {}
        #: All headers from the most recent response (e.g. X-Next-Cursor on CSV).
        #: Case-insensitive: ``client.last_headers.get("x-next-cursor")`` works.
        self.last_headers: Any = {}

    # ------------------------------------------------------------------ core

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Any = None,
        csv_body: Optional[str] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> Any:
        """Send a request. Returns parsed JSON, or text for CSV responses."""
        url = self.base_url + path
        query = {k: _fmt(v) for k, v in (params or {}).items() if v is not None}
        if query:
            url += "?" + urllib.parse.urlencode(query)

        hdrs = {
            "Authorization": f"Bearer {self.api_key}",
            # The server honours Accept over ?format=, and picks CSV if both
            # types are listed, so ask for exactly one.
            "Accept": "text/csv" if query.get("format") == "csv" else "application/json",
            "User-Agent": f"lastwar-farm-python/{__version__}",
        }
        data: Optional[bytes] = None
        if csv_body is not None:
            data = csv_body.encode("utf-8")
            hdrs["Content-Type"] = "text/csv"
        elif json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})

        attempt = 0
        while True:
            req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    self._record_limits(resp.headers)
                    return _decode(resp.read(), resp.headers.get("Content-Type", ""))
            except urllib.error.HTTPError as exc:
                self._record_limits(exc.headers)
                err = _to_api_error(exc)
                if isinstance(err, RateLimitedError) and attempt < self.max_retries:
                    attempt += 1
                    time.sleep(err.retry_after if err.retry_after else 2**attempt)
                    continue
                raise err from None

    def _record_limits(self, headers: Any) -> None:
        if headers is None:
            return
        self.last_headers = headers
        self.rate_limit = {
            "minute": headers.get("X-RateLimit-Remaining-Minute"),
            "day": headers.get("X-RateLimit-Remaining-Day"),
        }

    def _get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params)

    def _import(self, path: str, body: Dict[str, Any], csv: Optional[str],
                params: Optional[Mapping[str, Any]] = None) -> Any:
        if csv is not None:
            return self.request("POST", path, params=params, csv_body=csv)
        return self.request("POST", path, params=params, json_body=body)

    # ------------------------------------------------------- server (READ)

    def get_server(self) -> Any:
        """Aggregate server statistics. Requires a server key."""
        return self._get("/api/v1/server")

    def list_server_players(
        self,
        page: int = 1,
        page_size: int = 100,
        status: Optional[str] = None,       # ACTIVE | LEFT | ALL
        alliance_id: Optional[str] = None,
        sort_by: Optional[str] = None,      # name | currentPower | currentKills | ...
        order: Optional[str] = None,        # asc | desc
    ) -> Any:
        return self._get(
            "/api/v1/server/players", page=page, pageSize=page_size,
            status=status, allianceId=alliance_id, sortBy=sort_by, order=order,
        )

    def iter_server_players(self, page_size: int = 200, **filters: Any):
        """Yield every server player across all pages."""
        page = 1
        while True:
            resp = self.list_server_players(page=page, page_size=page_size, **filters)
            items = _items(resp)
            yield from items
            if not items or not _has_next(resp):
                return
            page += 1

    def get_player_history(
        self,
        player_id: str,
        metric: str = "power",              # power | kills | heroPower | totalHeroPower
        from_: Optional[str] = None,        # ISO date-time
        to: Optional[str] = None,
        page: int = 1,
        page_size: int = 100,
    ) -> Any:
        return self._get(
            f"/api/v1/server/players/{_q(player_id)}/history",
            metric=metric, **{"from": from_}, to=to, page=page, pageSize=page_size,
        )

    # ----------------------------------------------------- alliance (READ)

    def get_alliance(self) -> Any:
        """Basic info for the key's alliance. Requires an alliance key."""
        return self._get("/api/v1/alliance")

    def list_members(self, format: Optional[str] = None) -> Any:
        return self._get("/api/v1/alliance/members", format=format)

    def export_power(self, format: Optional[str] = None) -> Any:
        return self._get("/api/v1/alliance/members/power", format=format)

    def export_thp(self, format: Optional[str] = None) -> Any:
        return self._get("/api/v1/alliance/members/thp", format=format)

    def export_kills(self, format: Optional[str] = None) -> Any:
        return self._get("/api/v1/alliance/members/kills", format=format)

    def export_duels(self, format: Optional[str] = None) -> Any:
        """VS point scores."""
        return self._get("/api/v1/alliance/members/duels", format=format)

    def export_donations(self, format: Optional[str] = None) -> Any:
        return self._get("/api/v1/alliance/members/donations", format=format)

    def list_storms(self, type: Optional[str] = None,
                    from_: Optional[str] = None, to: Optional[str] = None) -> Any:
        """Storm events. ``type`` is CANYON or DESERT; dates are YYYY-MM-DD."""
        return self._get("/api/v1/alliance/storms", type=type, **{"from": from_}, to=to)

    def get_storm_assignments(self, event_id: str, format: Optional[str] = None) -> Any:
        return self._get(f"/api/v1/alliance/storms/{_q(event_id)}/assignments", format=format)

    def list_custom_events(self) -> Any:
        return self._get("/api/v1/alliance/custom-events")

    def export_custom_event_entries(self, event_id: str, format: Optional[str] = None) -> Any:
        return self._get(f"/api/v1/alliance/custom-events/{_q(event_id)}/entries", format=format)

    def list_seasons(self) -> Any:
        return self._get("/api/v1/alliance/seasons")

    def export_all(self) -> Any:
        """Everything for the alliance as one JSON bundle."""
        return self._get("/api/v1/alliance/export")

    def get_train_schedule(self, from_: str, to: str, format: Optional[str] = None) -> Any:
        """Saved Train schedules between two YYYY-MM-DD dates (future allowed)."""
        return self._get("/api/v1/alliance/train/schedule", **{"from": from_}, to=to, format=format)

    def export_train_history(self, limit: Optional[int] = None,
                             before: Optional[str] = None,
                             format: Optional[str] = None) -> Any:
        """One page (up to 100 dates), newest first. ``before`` is an exclusive
        YYYY-MM-DD cursor. JSON pages carry ``meta.nextCursor``; for CSV read
        ``client.last_headers.get("X-Next-Cursor")`` afterwards."""
        return self._get("/api/v1/alliance/train/history", limit=limit, before=before, format=format)

    def iter_train_history(self, before: Optional[str] = None):
        """Yield every historical Train date record, newest first."""
        while True:
            resp = self.export_train_history(limit=100, before=before)
            yield from _items(resp)
            before = (resp.get("meta") or {}).get("nextCursor") if isinstance(resp, dict) else None
            if not before:
                return

    # --------------------------------------------- alliance imports (WRITE)
    # Each entry identifies a member by ``memberId`` (preferred, exact) or
    # ``name`` (fuzzy). Pass ``csv=`` instead of entries to upload CSV text.

    def import_power(self, entries: Entries = (), csv: Optional[str] = None) -> Any:
        """entries: [{"memberId"|"name": ..., "power": int}]"""
        return self._import("/api/v1/alliance/members/power", {"entries": list(entries)}, csv)

    def import_thp(self, entries: Entries = (), csv: Optional[str] = None) -> Any:
        """entries: [{"memberId"|"name": ..., "totalHeroPower": int}]"""
        return self._import("/api/v1/alliance/members/thp", {"entries": list(entries)}, csv)

    def import_kills(self, entries: Entries = (), csv: Optional[str] = None) -> Any:
        """entries: [{"memberId"|"name": ..., "kills": int}]"""
        return self._import("/api/v1/alliance/members/kills", {"entries": list(entries)}, csv)

    def import_duels(self, entries: Entries = (), scored_on: Optional[str] = None,
                     csv: Optional[str] = None) -> Any:
        """VS points for one day. entries: [{"memberId"|"name": ..., "score": int}]"""
        body = _drop_none({"entries": list(entries), "scoredOn": scored_on})
        return self._import("/api/v1/alliance/members/duels", body, csv,
                            params={"scoredOn": scored_on} if csv is not None else None)

    def import_donations(self, entries: Entries = (), week_start: Optional[str] = None,
                         csv: Optional[str] = None) -> Any:
        """Weekly totals. entries: [{"memberId"|"name": ..., "total": int}]"""
        body = _drop_none({"entries": list(entries), "weekStart": week_start})
        return self._import("/api/v1/alliance/members/donations", body, csv,
                            params={"weekStart": week_start} if csv is not None else None)

    def import_storm_assignments(self, storm_type: str, event_date: str,
                                 entries: Entries = (), csv: Optional[str] = None) -> Any:
        """entries: [{"memberId"|"name": ..., "team": "A"|"B", "role": "STARTER"|"SUBSTITUTE"}]"""
        body = {"stormType": storm_type, "eventDate": event_date, "entries": list(entries)}
        return self._import("/api/v1/alliance/storms/assignments", body, csv,
                            params={"stormType": storm_type, "eventDate": event_date}
                            if csv is not None else None)

    def import_storm_scores(self, storm_type: str, event_date: str, entries: Entries,
                            default_team: Optional[str] = None) -> Any:
        """entries: [{"memberId"|"name": ..., "score": int}]"""
        body = _drop_none({"stormType": storm_type, "eventDate": event_date,
                           "defaultTeam": default_team, "entries": list(entries)})
        return self.request("POST", "/api/v1/alliance/storms/scores", json_body=body)

    def import_custom_event_entries(
        self, event_id: str, entries: Entries = (), recorded_at: Optional[str] = None,
        metric_id: Optional[str] = None, phase: Optional[str] = None,
        csv: Optional[str] = None, run_id: Optional[str] = None,
    ) -> Any:
        """entries: [{"memberId"|"name": ..., "value": number}]

        Runs-type events need ``run_id`` of a run that already exists (create
        the run in the lastwar.farm web UI; the API cannot). Not in the spec.
        """
        meta = {"recordedAt": recorded_at, "metricId": metric_id, "phase": phase,
                "runId": run_id}
        body = _drop_none({**meta, "entries": list(entries)})
        return self._import(f"/api/v1/alliance/custom-events/{_q(event_id)}/entries",
                            body, csv, params=meta if csv is not None else None)

    def import_train_history(self, entries: Optional[List[Mapping[str, Any]]] = None,
                             preview: bool = False,
                             idempotency_key: Optional[str] = None,
                             csv: Optional[str] = None) -> Any:
        """Import (or ``preview=True`` dry-run) historical Train rosters.

        Pass JSON ``entries`` (members by ID only) or ``csv`` text as exported
        by ``export_train_history(format="csv")`` (IDs or exact names).
        Each date replaces its whole roster. Existing dates need their current
        exported version; a null/blank version means create-only, and a stale
        one rejects the whole batch (STALE_ENTRY). Limits: 2 MiB, 100 dates,
        2,300 occupied seats. Needs a WRITE key whose creator is still an
        owner, admin or manager.

        Retry a failed commit with the *same* ``idempotency_key`` and payload;
        reusing a committed key with a different payload is REQUEST_CONFLICT.
        One is generated if omitted, so pass your own if you may retry.
        """
        if (entries is None) == (csv is None):
            raise ValueError("pass exactly one of entries= or csv=")
        key = idempotency_key or f"lwf-{uuid.uuid4().hex}"
        return self.request(
            "POST", "/api/v1/alliance/train/history",
            params={"preview": preview},
            json_body={"entries": list(entries)} if entries is not None else None,
            csv_body=csv, headers={"Idempotency-Key": key},
        )


# ---------------------------------------------------------------- helpers

def _fmt(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _q(segment: str) -> str:
    return urllib.parse.quote(str(segment), safe="")


def _drop_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _decode(raw: bytes, content_type: str) -> Any:
    text = raw.decode("utf-8") if raw else ""
    if "json" in content_type.lower():
        return json.loads(text) if text else None
    return text


def _to_api_error(exc: urllib.error.HTTPError) -> ApiError:
    code, message, details = None, exc.reason or "", None
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        err = payload.get("error", {}) if isinstance(payload, dict) else {}
        code, message, details = err.get("code"), err.get("message", message), err.get("details")
    except (ValueError, UnicodeDecodeError):
        pass
    retry_after = None
    if exc.headers is not None and exc.headers.get("Retry-After"):
        try:
            retry_after = float(exc.headers["Retry-After"])
        except ValueError:
            pass
    cls = RateLimitedError if exc.code == 429 else ApiError
    return cls(exc.code, code, str(message), details, retry_after)


def _items(resp: Any) -> List[Any]:
    """Paginated responses are ``{"data": [...], "meta": PaginationMeta}``."""
    data = resp.get("data") if isinstance(resp, dict) else None
    return data if isinstance(data, list) else []


def _has_next(resp: Any) -> bool:
    meta = resp.get("meta") if isinstance(resp, dict) else None
    return bool(isinstance(meta, dict) and meta.get("hasNextPage"))
