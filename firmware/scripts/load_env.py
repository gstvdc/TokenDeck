Import("env")

from pathlib import Path

project = Path(env.subst("$PROJECT_DIR"))
values = {}
for raw in (project / ".env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    values[key.strip()] = value.strip()

required = ("WIFI_SSID", "WIFI_PASSWORD", "CODEX_BRIDGE_URL",
            "CLAUDE_BRIDGE_URL", "REFRESH_INTERVAL_MS", "DEVICE_NAME")
missing = [key for key in required if not values.get(key)]
if missing:
    raise RuntimeError("Missing firmware/.env values: " + ", ".join(missing))

def c_string(value):
    return value.replace("\\", "\\\\").replace('"', '\\"')

header = project / "src" / "wifi_config.generated.h"
content = (
    "#pragma once\n"
    f'#define WIFI_SSID "{c_string(values["WIFI_SSID"])}"\n'
    f'#define WIFI_PASSWORD "{c_string(values["WIFI_PASSWORD"])}"\n'
    f'#define CODEX_BRIDGE_URL "{c_string(values["CODEX_BRIDGE_URL"])}"\n'
    f'#define CLAUDE_BRIDGE_URL "{c_string(values["CLAUDE_BRIDGE_URL"])}"\n'
    f'#define USE_CODEX {int(values.get("USE_CODEX", "1"))}\n'
    f'#define USE_CLAUDE {int(values.get("USE_CLAUDE", "1"))}\n'
    f'#define REFRESH_INTERVAL_MS {int(values["REFRESH_INTERVAL_MS"])}UL\n'
    f'#define DEVICE_NAME "{c_string(values["DEVICE_NAME"])}"\n'
)
if not header.exists() or header.read_text(encoding="utf-8") != content:
    header.write_text(content, encoding="utf-8")
