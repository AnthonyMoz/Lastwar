"""Offline tests: a local HTTP server stands in for lastwar.farm."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from lastwar_farm import ApiError, ConfigError, LastWarFarmClient, RateLimitedError

KEY = "fops_live_test"


class FakeApi(BaseHTTPRequestHandler):
    calls = []
    rate_limit_once = False

    def log_message(self, *args):
        pass

    def _send(self, status, body, ctype="application/json", extra=None):
        raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("X-RateLimit-Remaining-Minute", "59")
        self.send_header("X-RateLimit-Remaining-Day", "4999")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def _handle(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode() if length else None
        FakeApi.calls.append({"method": self.command, "path": url.path,
                              "query": parse_qs(url.query), "body": body,
                              "headers": dict(self.headers)})
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            return self._send(401, {"error": {"code": "INVALID_KEY", "message": "bad key"}})
        if FakeApi.rate_limit_once:
            FakeApi.rate_limit_once = False
            return self._send(429, {"error": {"code": "RATE_LIMITED", "message": "slow"}},
                              extra={"Retry-After": "0"})
        if url.path == "/api/v1/server":
            return self._send(403, {"error": {"code": "TENANT_MISMATCH", "message": "alliance key"}})
        if url.path == "/api/v1/alliance/members" and "format=csv" in url.query:
            return self._send(200, "memberId,name\nm1,Alpha\n", ctype="text/csv")
        if url.path == "/api/v1/server/players":
            page = int(parse_qs(url.query)["page"][0])
            return self._send(200, {"data": [{"id": f"p{page}"}],
                                    "meta": {"page": page, "pageSize": 1, "total": 2,
                                             "totalPages": 2, "hasNextPage": page < 2}})
        return self._send(200, {"ok": True, "path": url.path})

    do_GET = do_POST = _handle


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeApi)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeApi.calls.clear()
        self.client = LastWarFarmClient(KEY, base_url=self.base, dotenv_path=None)

    def test_missing_key(self):
        import os
        os.environ.pop("LASTWAR_FARM_API_KEY", None)
        with self.assertRaises(ConfigError):
            LastWarFarmClient(base_url=self.base, dotenv_path=None)

    def test_get_sends_bearer_and_records_limits(self):
        self.assertEqual(self.client.get_alliance()["path"], "/api/v1/alliance")
        self.assertEqual(FakeApi.calls[0]["headers"]["Authorization"], f"Bearer {KEY}")
        self.assertEqual(self.client.rate_limit, {"minute": "59", "day": "4999"})

    def test_csv_response_returned_as_text(self):
        self.assertTrue(self.client.list_members(format="csv").startswith("memberId,name"))

    def test_error_code_parsed(self):
        with self.assertRaises(ApiError) as cm:
            self.client.get_server()
        self.assertEqual((cm.exception.status, cm.exception.code), (403, "TENANT_MISMATCH"))

    def test_bad_key(self):
        bad = LastWarFarmClient("nope", base_url=self.base, dotenv_path=None)
        with self.assertRaises(ApiError) as cm:
            bad.get_alliance()
        self.assertEqual(cm.exception.code, "INVALID_KEY")

    def test_retries_on_429(self):
        FakeApi.rate_limit_once = True
        self.assertTrue(self.client.get_alliance()["ok"])
        self.assertEqual(len(FakeApi.calls), 2)

    def test_429_raises_when_retries_exhausted(self):
        FakeApi.rate_limit_once = True
        client = LastWarFarmClient(KEY, base_url=self.base, max_retries=0, dotenv_path=None)
        with self.assertRaises(RateLimitedError):
            client.get_alliance()

    def test_json_import_body(self):
        self.client.import_duels([{"name": "Alpha", "score": 123}], scored_on="2026-11-16")
        call = FakeApi.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(json.loads(call["body"]),
                         {"entries": [{"name": "Alpha", "score": 123}], "scoredOn": "2026-11-16"})

    def test_csv_import_moves_meta_to_query(self):
        self.client.import_donations(csv="name,total\nAlpha,5\n", week_start="2026-11-16")
        call = FakeApi.calls[0]
        self.assertEqual(call["headers"]["Content-Type"], "text/csv")
        self.assertEqual(call["query"]["weekStart"], ["2026-11-16"])

    def test_train_history_idempotency_and_preview(self):
        self.client.import_train_history([{"date": "2026-11-01", "expectedVersion": None}],
                                         preview=True)
        call = FakeApi.calls[0]
        self.assertEqual(call["query"]["preview"], ["true"])
        self.assertTrue(call["headers"]["Idempotency-Key"].startswith("lwf-"))
        self.assertEqual(json.loads(call["body"])["entries"][0]["expectedVersion"], None)

    def test_iter_server_players_paginates(self):
        ids = [p["id"] for p in self.client.iter_server_players(page_size=1)]
        self.assertEqual(ids, ["p1", "p2"])

    def test_path_segments_are_escaped(self):
        self.client.get_storm_assignments("a/b")
        self.assertEqual(FakeApi.calls[0]["path"], "/api/v1/alliance/storms/a%2Fb/assignments")


if __name__ == "__main__":
    unittest.main()
