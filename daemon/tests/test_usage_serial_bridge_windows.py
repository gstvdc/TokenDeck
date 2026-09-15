import json

from daemon.usage_serial_bridge_windows import last_active_provider, parse_antigravity_usage


def test_parses_only_gemini_group_from_antigravity_usage():
    usage = {
        "command": {
            "data": {
                "groups": [
                    {
                        "name": "Gemini Models",
                        "buckets": [
                            {
                                "window": "weekly",
                                "remaining_fraction": 0.433,
                                "reset_time": "2026-09-18T15:15:12Z",
                            },
                            {
                                "window": "5h",
                                "remaining_fraction": 0.7944,
                                "reset_time": "2026-09-15T02:44:56Z",
                            },
                        ],
                    },
                    {
                        "name": "Claude and GPT models",
                        "buckets": [
                            {"window": "weekly", "remaining_fraction": 0},
                            {"window": "5h", "remaining_fraction": 1, "disabled": True},
                        ],
                    },
                ]
            }
        }
    }

    payload = parse_antigravity_usage(json.dumps(usage), now=1_789_736_000)

    assert payload == {
        "p": "gemini",
        "s": 20.6,
        "sr": 0,
        "w": 56.7,
        "wr": 8_512,
        "st": "allowed",
        "ok": True,
        "t": 1_789_736_000,
    }


def test_rejects_usage_without_the_gemini_group():
    assert parse_antigravity_usage('{"command":{"data":{"groups":[]}}}') is None


def test_detects_provider_with_most_recent_conversation_activity(tmp_path):
    roots = {name: tmp_path / name for name in ("codex", "claude", "gemini")}
    for index, root in enumerate(roots.values()):
        root.mkdir()
        record = root / "conversation.jsonl"
        record.write_text("{}", encoding="utf-8")
        record.touch()
        # Make each source one minute newer than the previous one.
        import os
        os.utime(record, (1_000 + index * 60, 1_000 + index * 60))

    assert last_active_provider(roots) == "gemini"
