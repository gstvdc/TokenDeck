import json

from daemon.codex_usage_daemon_windows import read_codex_payload


def test_reads_latest_codex_rate_limits_only(tmp_path):
    session = tmp_path / "2026" / "09" / "03" / "rollout.jsonl"
    session.parent.mkdir(parents=True)
    records = [
        {"payload": {"type": "message", "content": "must stay private"}},
        {"payload": {"type": "token_count", "rate_limits": {
            "primary": {"used_percent": 36, "resets_at": 1600},
            "secondary": {"used_percent": 84, "resets_at": 2200},
            "plan_type": "plus", "rate_limit_reached_type": None,
        }}},
    ]
    session.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

    payload = read_codex_payload(tmp_path, now=1000)

    assert payload["p"] == "codex"
    assert payload["s"] == 36
    assert payload["sr"] == 10
    assert payload["w"] == 84
    assert payload["wr"] == 20
    assert "content" not in payload


def test_ignores_trailing_empty_rate_limits(tmp_path):
    session = tmp_path / "2026" / "09" / "03" / "rollout.jsonl"
    session.parent.mkdir(parents=True)
    records = [
        {"payload": {"type": "token_count", "rate_limits": {
            "limit_id": "codex",
            "primary": {"used_percent": 42, "resets_at": 1600},
            "secondary": {"used_percent": 50, "resets_at": 2200},
            "plan_type": "plus",
        }}},
        # Real-world trailing record with primary=None (e.g. limit_id=premium)
        {"payload": {"type": "token_count", "rate_limits": {
            "limit_id": "premium",
            "primary": None,
            "secondary": None,
            "plan_type": "plus",
        }}},
    ]
    session.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

    payload = read_codex_payload(tmp_path, now=1000)
    assert payload is not None
    assert payload["s"] == 42
    assert payload["w"] == 50


def test_fallback_to_previous_session_if_latest_has_no_limits(tmp_path):
    older_session = tmp_path / "2026" / "09" / "02" / "old.jsonl"
    newer_session = tmp_path / "2026" / "09" / "03" / "new.jsonl"
    older_session.parent.mkdir(parents=True, exist_ok=True)
    newer_session.parent.mkdir(parents=True, exist_ok=True)

    records_old = [
        {"payload": {"type": "token_count", "rate_limits": {
            "primary": {"used_percent": 75, "resets_at": 1600},
            "secondary": {"used_percent": 80, "resets_at": 2200},
            "plan_type": "plus",
        }}},
    ]
    records_new = [
        {"payload": {"type": "message", "content": "Just started conversation"}},
    ]

    older_session.write_text("\n".join(json.dumps(r) for r in records_old), encoding="utf-8")
    import time
    newer_session.write_text("\n".join(json.dumps(r) for r in records_new), encoding="utf-8")
    # Ensure newer_session has a distinctly newer mtime
    import os
    os.utime(older_session, (500, 500))
    os.utime(newer_session, (1000, 1000))

    payload = read_codex_payload(tmp_path, now=1000)
    assert payload is not None
    assert payload["s"] == 75
    assert payload["w"] == 80

