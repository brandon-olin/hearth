#!/usr/bin/env python3
"""
smoke_coach.py — execute the AI coach / journal / chat endpoint surface.

Why this exists
---------------
coach-001..007, chat-001, journal-001/002 are all implemented and mounted
(ai_router in main.py), but sit at passes=false in feature_list.json awaiting
verification. "Registered in main.py" is NOT proof of "works" — journal-001
shipped with a missing `select` import that only surfaced on execution. This
script executes every endpoint for real and records what happened.

Per root CLAUDE.md → "Utility scripts": stdlib only. No requests, no httpx.

Usage
-----
    export HEARTH_EMAIL='you@example.com'
    export HEARTH_PASSWORD='...'
    python3 scripts/smoke_coach.py                 # read-only tier (free, safe)
    python3 scripts/smoke_coach.py --write         # + mutating & LLM-calling tier
    python3 scripts/smoke_coach.py --api http://localhost:1338

Tiers
-----
  read  (default) GET endpoints only. No data written, no LLM tokens spent.
                  Catches import errors, broken queries, serialization faults,
                  scope bugs — the bulk of what "wired but broken" looks like.
  write (--write) POST/PATCH endpoints. Some invoke the configured AI provider
                  and WILL consume tokens and create rows. Opt-in on purpose.

Output
------
  Human summary on stdout, plus structured results at
  .agent-logs/coach-smoke.json (gitignored).
  Exit 0 if every executed check passed, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

DEFAULT_API = os.environ.get("HEARTH_API", "http://localhost:1339")
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".agent-logs")
OUT_PATH = os.path.join(LOG_DIR, "coach-smoke.json")

# Endpoints that legitimately return a non-2xx or empty body in a clean install.
# Anything else non-2xx is a failure worth looking at.
TOLERATED = {
    # (path_key): set of acceptable status codes beyond 2xx
    "GET /ai/coach/digest": {404},          # no digest generated yet
    "GET /ai/profile": {404},               # profile not bootstrapped yet
}

_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def request(
    base: str,
    method: str,
    path: str,
    token: str | None = None,
    body: dict | None = None,
    params: dict | None = None,
    timeout: int = 60,
) -> tuple[int, object, float]:
    """Returns (status_code, parsed_body_or_text, elapsed_ms). Never raises on HTTP error."""
    url = f"{base}{path}"
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)

    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ctx) as resp:
            raw = resp.read()
            elapsed = (time.perf_counter() - started) * 1000
            if not raw:
                return resp.status, None, elapsed
            try:
                return resp.status, json.loads(raw), elapsed
            except json.JSONDecodeError:
                return resp.status, raw.decode("utf-8", "replace")[:400], elapsed
    except urllib.error.HTTPError as e:
        elapsed = (time.perf_counter() - started) * 1000
        raw = e.read()
        try:
            return e.code, json.loads(raw), elapsed
        except Exception:
            return e.code, raw.decode("utf-8", "replace")[:400], elapsed
    except urllib.error.URLError as e:
        elapsed = (time.perf_counter() - started) * 1000
        return 0, f"CONNECTION FAILED: {e.reason}", elapsed
    except Exception as e:  # timeouts, etc.
        elapsed = (time.perf_counter() - started) * 1000
        return 0, f"{type(e).__name__}: {e}", elapsed


def excerpt(payload: object, limit: int = 220) -> str:
    if payload is None:
        return "(empty body)"
    if isinstance(payload, str):
        return payload[:limit]
    try:
        return json.dumps(payload)[:limit]
    except Exception:
        return str(payload)[:limit]


class Runner:
    def __init__(self, base: str, token: str):
        self.base = base
        self.token = token
        self.results: list[dict] = []

    def check(
        self,
        feature: str,
        method: str,
        path: str,
        *,
        body: dict | None = None,
        params: dict | None = None,
        tier: str = "read",
        note: str = "",
        timeout: int = 60,
    ) -> tuple[int, object]:
        key = f"{method} {path}"
        status, payload, ms = request(
            self.base, method, path, token=self.token, body=body, params=params, timeout=timeout
        )
        ok = 200 <= status < 300 or status in TOLERATED.get(key, set())
        self.results.append(
            {
                "feature": feature,
                "endpoint": key,
                "tier": tier,
                "status": status,
                "ok": ok,
                "ms": round(ms, 1),
                "note": note,
                "response": excerpt(payload),
            }
        )
        flag = "PASS" if ok else "FAIL"
        print(f"  [{flag}] {status:>3}  {key:<48} {ms:7.0f}ms  {feature}")
        if not ok:
            print(f"         └─ {excerpt(payload, 300)}")
        return status, payload

    def skip(self, feature: str, endpoint: str, why: str) -> None:
        self.results.append(
            {
                "feature": feature,
                "endpoint": endpoint,
                "tier": "skipped",
                "status": None,
                "ok": None,
                "ms": 0,
                "note": why,
                "response": "",
            }
        )
        print(f"  [SKIP]      {endpoint:<48}          {why}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke-test the Hearth AI coach/journal/chat surface.")
    ap.add_argument("--api", default=DEFAULT_API, help=f"API base URL (default {DEFAULT_API})")
    ap.add_argument("--write", action="store_true", help="also run mutating / LLM-calling endpoints")
    ap.add_argument("--email", default=os.environ.get("HEARTH_EMAIL"))
    ap.add_argument("--password", default=os.environ.get("HEARTH_PASSWORD"))
    args = ap.parse_args()

    if not args.email or not args.password:
        print("ERROR: set HEARTH_EMAIL and HEARTH_PASSWORD (or pass --email/--password).")
        return 2

    base = args.api.rstrip("/")
    print(f"\nHearth coach/journal/chat smoke test")
    print(f"API:  {base}")
    print(f"Tier: {'read + write (LLM calls enabled)' if args.write else 'read-only'}\n")

    # ── Reachability ──────────────────────────────────────────────────────────
    status, payload, _ = request(base, "GET", "/openapi.json", timeout=15)
    if status != 200:
        print(f"ERROR: API not reachable at {base} ({excerpt(payload)})")
        print("Start it with ./init.sh (dev API on :1339) and retry.")
        return 2
    route_count = len(payload.get("paths", {})) if isinstance(payload, dict) else 0
    print(f"OpenAPI reachable — {route_count} routes registered\n")

    # ── Auth ──────────────────────────────────────────────────────────────────
    status, payload, _ = request(
        base, "POST", "/auth/login", body={"email": args.email, "password": args.password}
    )
    if status != 200 or not isinstance(payload, dict) or "access_token" not in payload:
        print(f"ERROR: login failed ({status}) — {excerpt(payload)}")
        return 2
    token = payload["access_token"]
    user = payload.get("user", {}) or {}
    print(f"Authenticated as {user.get('email', args.email)}\n")

    r = Runner(base, token)

    # ── Tier 1: read-only ─────────────────────────────────────────────────────
    print("── read-only ──────────────────────────────────────────────────────")
    r.check("ai settings", "GET", "/ai/settings")
    r.check("ai usage", "GET", "/ai/usage")
    r.check("chat-001", "GET", "/ai/conversations")
    r.check("chat-001", "GET", "/ai/conversations/search", params={"q": "test"})
    r.check("coach-003", "GET", "/ai/coach/tones")
    r.check("coach-002", "GET", "/ai/coach/digest")
    r.check("coach-001", "GET", "/ai/profile")
    r.check("coach-001b", "GET", "/ai/profile/updates")
    r.check("coach-007", "GET", "/ai/profile/versions")

    # Journal collection discovery — also exercises the kind='journal' path that
    # backfill_journal_kind / infra-004 is concerned with.
    note_id = None
    status, payload = r.check("journal-001", "GET", "/collections")
    journal_col = None
    if status == 200:
        items = payload.get("items", payload) if isinstance(payload, dict) else payload
        if isinstance(items, list):
            journal_col = next((c for c in items if c.get("kind") == "journal"), None)
    if journal_col:
        print(f"         └─ journal collection: {journal_col.get('name')} ({journal_col['id']})")
    else:
        print("         └─ WARNING: no kind='journal' collection found — "
              "coach narrative fetch and journal signal extraction gate on this")

    # ── Tier 2: write / LLM ───────────────────────────────────────────────────
    if not args.write:
        print("\n── write tier skipped (pass --write to enable) ─────────────────────")
        for feat, ep in [
            ("coach-001", "POST /ai/profile/bootstrap"),
            ("coach-002", "POST /ai/coach/digest/generate"),
            ("journal-001", "POST /ai/journal/start"),
            ("journal-001", "POST /ai/journal/save"),
            ("chat-001", "POST /ai/chat"),
            ("coach-002", "POST /ai/journal-signals/backfill"),
        ]:
            r.skip(feat, ep, "write tier not enabled")
    else:
        print("\n── write + LLM (consumes tokens, creates rows) ─────────────────────")

        r.check("coach-001", "POST", "/ai/profile/bootstrap", body={}, tier="write",
                note="invokes LLM", timeout=180)
        r.check("coach-002", "POST", "/ai/coach/digest/generate", body={}, tier="write",
                note="invokes LLM", timeout=180)

        # chat-001 — round trip, then read the conversation back.
        status, payload = r.check(
            "chat-001", "POST", "/ai/chat",
            body={"content": "Smoke test: reply with the single word OK."},
            tier="write", note="invokes LLM", timeout=180,
        )
        conv_id = payload.get("conversation_id") if isinstance(payload, dict) else None
        if conv_id:
            r.check("chat-001", "GET", f"/ai/conversations/{conv_id}", tier="write",
                    note="read back the conversation just created")
        else:
            r.skip("chat-001", "GET /ai/conversations/{id}", "no conversation_id returned from /ai/chat")

        # journal-001/002 — needs a note in the journal collection.
        if journal_col:
            status, payload = r.check(
                "journal-001", "POST", f"/collections/{journal_col['id']}/ensure-today",
                body={}, tier="write", note="get/create today's journal note",
            )
            if isinstance(payload, dict):
                note_id = payload.get("note_id") or (payload.get("note") or {}).get("id")

        if note_id:
            r.check("journal-001", "POST", "/ai/journal/start",
                    body={"note_id": note_id}, tier="write", note="mount call, no mode", timeout=120)
            r.check("journal-002", "POST", "/ai/journal/start",
                    body={"note_id": note_id, "mode": "mood", "local_hour": 20},
                    tier="write", note="mode=mood, invokes LLM", timeout=180)
            r.check("journal-001", "POST", "/ai/journal/save",
                    body={"conversation_id": conv_id, "content_md": "Smoke test entry.",
                          "include_transcript": False},
                    tier="write", note="expect 4xx if conversation_id is not a journal conversation")
        else:
            r.skip("journal-001", "POST /ai/journal/start", "no journal note_id available")
            r.skip("journal-001", "POST /ai/journal/save", "no journal note_id available")

        r.check("coach-002", "POST", "/ai/journal-signals/backfill",
                params={"only_outdated_version": "true"}, body={}, tier="write",
                note="invokes LLM per journal entry", timeout=300)

    # ── Report ────────────────────────────────────────────────────────────────
    executed = [x for x in r.results if x["ok"] is not None]
    passed = [x for x in executed if x["ok"]]
    failed = [x for x in executed if not x["ok"]]
    skipped = [x for x in r.results if x["ok"] is None]

    print("\n── summary ────────────────────────────────────────────────────────")
    print(f"  passed:  {len(passed)}")
    print(f"  failed:  {len(failed)}")
    print(f"  skipped: {len(skipped)}")

    if failed:
        print("\n  FAILURES:")
        for x in failed:
            print(f"    {x['status']:>3}  {x['endpoint']:<46} {x['feature']}")
            print(f"         {x['response'][:200]}")

    by_feature: dict[str, dict[str, int]] = {}
    for x in executed:
        d = by_feature.setdefault(x["feature"], {"pass": 0, "fail": 0})
        d["pass" if x["ok"] else "fail"] += 1
    print("\n  per feature:")
    for feat in sorted(by_feature):
        d = by_feature[feat]
        verdict = "clean" if d["fail"] == 0 else f"{d['fail']} FAILING"
        print(f"    {feat:<16} {d['pass']} passed, {verdict}")

    os.makedirs(LOG_DIR, exist_ok=True)
    with open(OUT_PATH, "w") as fh:
        json.dump(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "api": base,
                "tier": "read+write" if args.write else "read",
                "route_count": route_count,
                "totals": {"passed": len(passed), "failed": len(failed), "skipped": len(skipped)},
                "results": r.results,
            },
            fh,
            indent=2,
        )
    print(f"\n  structured results → {os.path.relpath(OUT_PATH)}")
    print("\n  NOTE: a clean read-only run proves routing, auth, queries and")
    print("  serialization. It does NOT prove the LLM-backed behaviour — run")
    print("  --write before flipping any coach/journal/chat flag to passes=true.\n")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
