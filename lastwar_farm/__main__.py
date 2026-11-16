"""Command line: ``python -m lastwar_farm <command>``.

  ping             Check the key works and report which tenant it belongs to
  alliance         Alliance info              (alliance key)
  members          Alliance members           (alliance key)
  export           Full alliance JSON bundle  (alliance key)
  server           Server statistics          (server key)
  players          First page of server players (server key)
"""

from __future__ import annotations

import argparse
import json
import sys

from .client import LastWarFarmClient
from .errors import ApiError, LastWarFarmError


def _ping(client: LastWarFarmClient) -> int:
    """Try the alliance endpoint, then the server endpoint."""
    for label, call in (("alliance", client.get_alliance), ("server", client.get_server)):
        try:
            data = call()
        except ApiError as exc:
            if exc.code == "TENANT_MISMATCH":
                continue
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1
        print(f"OK: connected to {client.base_url} with a {label} key")
        print(f"Rate limit remaining: {client.rate_limit}")
        print(json.dumps(data, indent=2))
        return 0
    print("FAILED: key was rejected by both alliance and server endpoints", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lastwar-farm", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["ping", "alliance", "members", "export",
                                            "server", "players"])
    parser.add_argument("--base-url", help="Override API host")
    args = parser.parse_args(argv)

    try:
        client = LastWarFarmClient(base_url=args.base_url)
        if args.command == "ping":
            return _ping(client)
        result = {
            "alliance": client.get_alliance,
            "members": client.list_members,
            "export": client.export_all,
            "server": client.get_server,
            "players": client.list_server_players,
        }[args.command]()
    except LastWarFarmError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2) if not isinstance(result, str) else result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
