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
