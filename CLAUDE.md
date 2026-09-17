# Project context

ESP32 firmware for a desk-side Claude Code usage monitor. Each supported board
lives in its own `firmware/src/boards/<name>/` folder and is selected via
PlatformIO's `build_src_filter`. Adding a board means dropping in a new folder
+ a new `[env:...]` block — `main.cpp`, `ui.cpp`, and `splash.cpp` never see
board-specific code. See [`docs/porting/adding-a-board.md`](docs/porting/adding-a-board.md).

One port ships today:

- `boards/cyd_28/` — ESP32-2432S028R "CYD 2.8" (classic ESP32, ILI9341 320×240 SPI TFT, XPT2046 resistive touch). Build env: `cyd_28`. No PMU, no IMU, no PSRAM. Talks to the host over **USB serial** (`USE_USB_SERIAL_BRIDGE`, via `usage_serial_bridge_windows.py`), not BLE — `ble.cpp`/`chime.cpp`/`es8311.c` are excluded from this env's `build_src_filter`. No dedicated PWR key: a screen tap starts/restarts pairing (`BoardCaps.has_pwr_button = false`).
- `boards/template/` — copy this to bootstrap a new port; TODO-scaffolded, no board-specific values.

**Earlier Waveshare AMOLED/LCD ports (2.16", 1.8", 1.8" C6, 2.16" C6, 2.06",
1.54", LCD-4) and the SDL2 desktop simulator were retired** when the project
pivoted to the CYD board and a Windows-first GUI/serial-bridge flow — their
`platformio.ini` envs are gone, so that firmware source was removed rather
than kept as dead weight. Find it in git history (pre-rebrand commits) if you
need to resurrect a port; the HAL (`firmware/src/hal/`) and
`docs/porting/adding-a-board.md` still describe how.

The shared code calls a small HAL (`firmware/src/hal/`) that each board
implements: display, touch, input, power, IMU. Optional features are guarded
by `BoardCaps` (runtime) and `BOARD_HAS_*` (compile-time) rather than
`#ifdef BOARD_*` in shared files — `main.cpp`/`ui.cpp` branch on
`board_caps().has_pwr_button` instead of `#ifdef BOARD_CYD_28` for this
reason. This file is for future Claude Code sessions to bootstrap quickly.
Read this first.

## Hardware (critical pins) — CYD 2.8" (`cyd_28`)

- Display: **ILI9341** 320×240 via SPI (MISO=12, MOSI=13, SCLK=14, CS=15, DC=2, RST=-1 [tied high], BL=21).
- Touch: **XPT2046** via a second SPI bus (SCLK=25, MOSI=32, MISO=39, CS=33, INT=36), resistive — calibration bounds `TOUCH_MIN/MAX_X/Y` in `board.h`.
- No PMU, no IMU, no IO expander, no audio codec.
- Buttons: GPIO 0 (BOOT → Space/voice-mode) only. No secondary button, no PWR key.
- Host link: USB serial (see "Daemon / host side" below), not BLE.

## Architecture

```text
firmware/src/
  hal/                      — board-agnostic interfaces shared code calls into
    board_caps.h            — runtime BoardCaps struct (W, H, button_count, has_* flags)
    display_hal.h           — init / begin / set_brightness / draw_bitmap / tick / round_area
    touch_hal.h             — init / read(&x, &y, &pressed)
    input_hal.h             — init / is_held(PRIMARY|SECONDARY)
    power_hal.h             — init / tick / battery_pct / is_charging / pwr_pressed (edge)
    imu_hal.h               — init / tick / rotation_quadrant
  boards/
    cyd_28/                 — ILI9341 SPI TFT + XPT2046 touch, no PMU/IMU/PSRAM, USB serial link
    template/               — copy this to bootstrap a new port
  main.cpp                  — setup() + loop(): HAL calls only, zero #ifdef BOARD_*
  ui.{h,cpp}                — UI screens (splash, usage, bluetooth/pairing). compute_layout() picks fonts/positions from board_caps() (responsive — current breakpoint: H >= 460 → large, else compact)
  splash.{h,cpp}            — 20×20 pixel-art engine. CELL = min(W,H)/20, centered.
  ble.{h,cpp}               — NimBLE peripheral: custom data service + HID keyboard (excluded from the cyd_28 build; see USB serial bridge below)
  data.h                    — UsageData struct
  icons.h                   — icon arrays. Battery (5×) are RGB565A8 with alpha; rest are raw RGB565.
  logo.h                    — 80×80 RGB565 logo
  font_*.c                  — pre-compiled LVGL 9 bitmap fonts (Tiempos 56/34, Styrene 48/28/24/20/16/14/12, Mono 32/18)
  splash_animations.h       — generated, do not hand-edit
docs/porting/               — adding-a-board.md, hal-contract.md, capability-flags.md
```

Each board folder contains: `board.h` (pins, I2C addresses, `BOARD_HAS_*` flags),
`board_init.cpp` (Wire.begin + any IO expander), `display.cpp`, `touch.cpp`,
`input.cpp`, `power.cpp`, `imu.cpp`, `caps.cpp` (the `BoardCaps` instance), plus
any board-private hardware drivers. PlatformIO's `build_src_filter` includes
shared code + one board's folder per env.

## Build / flash

```bash
pio run -d firmware -e cyd_28                                     # build
pio run -d firmware -e cyd_28 -t upload --upload-port /dev/ttyACM0  # flash on Linux/macOS
```

If `pio` isn't on PATH: try `~/.platformio/penv/bin/pio` (or its Windows
`Scripts\pio.exe`), or `brew install platformio` on macOS. On Windows, use
`scripts\flash-cyd.ps1` (also invoked by `tokendeck-record.cmd`) — it
resolves the right port automatically.

## QA your own UI changes — don't ask the user

The firmware's `screenshot` serial command (LVGL framebuffer dump) and the `screenshot.sh` wrapper that drove it were removed — both required `LV_USE_SNAPSHOT`, which `cyd_28` builds with off (`-DLV_USE_SNAPSHOT=0` in `platformio.ini`, no PSRAM to spare). UI changes must be eyeballed on real hardware. A future PSRAM-equipped board that enables `LV_USE_SNAPSHOT` would need to reintroduce this tooling.

The boot screen is `SCREEN_SPLASH` and only advances on a physical button press (or a screen tap on `cyd_28`, which has no PWR key), so a fresh flash will sit on the splash. To exercise the screen you're actually editing without a physical button press, **temporarily change the default boot screen** in `main.cpp` (search for `ui_show_screen(SCREEN_SPLASH);`) to `SCREEN_USAGE` / `SCREEN_CONTROLLER` / `SCREEN_BLUETOOTH`, do your iteration, then revert before committing.

## Critical gotchas

1. **pioarduino platform required.** GFX Library for Arduino needs Arduino Core 3.x (`esp32-hal-periman.h`), not the 2.x that standard `espressif32` ships. We pin `pioarduino/platform-espressif32` 55.03.38-1.
2. **LVGL 9 font patching.** `lv_font_conv` outputs LVGL 8 format. Must remove `#if LVGL_VERSION_MAJOR >= 8` guards, drop `.cache` field, add `.release_glyph`, `.kerning`, `.static_bitmap`, `.fallback`, `.user_data`. Without patching, fonts render invisible. Full regeneration recipe: `docs/fonts.md`.
3. **Touch reading is centralized inside each board's `touch.cpp`.** The HAL `touch_hal_read()` is called once per loop from `my_touch_cb`; the board's implementation owns its latched `touch_pressed/x/y` state. Don't call the underlying controller from anywhere else — a full transaction from a concurrent caller can consume the sample the main loop expected.
4. **LVGL RGB565A8 is planar.** `w*h` RGB565 pixels followed by `w*h` alpha bytes; `data_size = w*h*3`, `stride = w*2`. Use `init_icon_dsc_rgb565a8()` for icons that overlap non-uniform backgrounds (e.g. battery over splash). Lucide source PNGs are black-on-transparent — converter must tint to white or icons render invisible. See `tools/png_to_lvgl.js`.
5. **Per-board pre-init is `board_init()`.** Each board's `board_init.cpp` brings up `Wire`/SPI and any reset-gating IO expander BEFORE `display_hal_init()`. A board with an IO expander gating the LCD/touch reset lines must release it before `gfx->begin()` or the panel silently fails to probe.
6. **No `#ifdef BOARD_*` in shared code.** The whole point of the HAL refactor — if you're about to add one, you probably want a `BoardCaps` field or a per-board file instead (e.g. `board_caps().has_pwr_button`, not `#ifdef BOARD_CYD_28`). See `docs/porting/capability-flags.md`.
7. **QSPI/AMOLED-specific rotation and column-offset tricks (CPU strip rotation, `display_hal_round_area` even-alignment, GRAM column offsets) don't apply to `cyd_28`'s plain SPI ILI9341** — they're relevant again only if a QSPI AMOLED port is revived from git history. See `docs/porting/hal-contract.md` for what each HAL function must do in general.

## Icons

`tools/png_to_lvgl.js <input.png> <symbol> [W_MACRO] [H_MACRO] [--tint=RRGGBB | --no-tint]` converts an alpha PNG to RGB565A8. Default tint is white (`0xFFFFFF`) — necessary for Lucide PNGs. Splice output into `firmware/src/icons.h` and use `init_icon_dsc_rgb565a8()` in ui.cpp. Currently only the 5 battery icons use this format; the rest are still raw RGB565 baked over the panel background, fine because they live inside opaque zones.

## Splash animations

17 official Anthropic Clawd animations (core poses + persona scenes), archived
with full provenance in `research/clawd-official/`. Pipeline:

```bash
node tools/convert_official_clawd.js            # → firmware/src/splash_animations.h
node tools/convert_official_clawd.js --verify DIR   # + per-animation PNGs for eyeballing
```

Requires ImageMagick; Laptop and Soccer convert from their Lottie exports
(crisp) rather than GIFs. Frames are bounding-box crops on the official 55×37
art stage (ox/oy = stage offset — every animation shares one idle-Clawd
position, so transitions are seamless), one byte per cell into a per-animation
≤16-color RGB565 palette (index 0 = background, true black), per-frame hold ms
with duplicates collapsed (~400 KB total). The converter also: detects each
animation's **loop region** (gait cycles, scene middles; sailing scene's is
located by cross-matching the standalone sailing-loop asset, which is not
emitted), synthesizes the **eyes** (transparent holes in the source GIFs) as
`#141413` ink via border flood-fill, and applies two contrast recolors
(trumpet notes → ivory, magnifier fedora → gray) via component analysis.

The splash engine (`splash.cpp`) plays intro → loop → outro on a **60×60
stage** (`SPLASH_GRID`, cell = min(W,H)/60 → 8 px on 480, 6 px on 368, 4 px on
240): loops hold until released (walk arrival, scene timer, rotation), so
switches always pass through the shared idle pose. Walkers translate with
foot-locked per-frame schedules and mirror when heading left. Usage-rate
groups pick animations by name; the same rate drives the **corner mascot** on
the usage screen (`splash_mascot_*` on `BOARD_HAS_PSRAM` boards; no-PSRAM
boards like `cyd_28` fall back to the static `clawd_still.h` icon) — idle
stills, rate-scaled acts, and walk-off/lurk/walk-back trips. Default boot screen.

**Where the animations come from / finding new ones:** all assets are plain
files under `https://claude.ai/images/clawd/{core,persona}/…` — static assets
are not Cloudflare-gated, only HTML routes are. The asset server returns a
real GIF for a valid filename and an HTML catch-all (both HTTP 200) otherwise,
so **name probing works**: fetch `Clawd-<Name>.gif` and check the magic bytes.
Seven current animations are referenced by no shipped bundle and were found
exactly this way (Anthropic stages seasonal drops — Soccer appeared for the
World Cup). To hunt for new ones: run `research/clawd-official/fetch.sh`
(extend its probe list), and grep a fresh desktop .deb's `ion-dist/` bundles
for `/images/` paths (`research/clawd-official/CLAUDE.md` documents the full
methodology, including the Lottie sources and the assets-proxy).


## User profile / preferences

See `~/.claude/projects/.../memory/` files for persistent context (user is an embedded-beginner senior dev, brand-conscious, prefers iterative UI refinement, dislikes me authoring my own art when third-party assets are intended). Always read those memory files at session start.

## Recent session highlights

- **Repo-wide cleanup + CYD-only doc rewrite (2026-09-16).** Removed the
  now-orphaned Waveshare/sim board source (their `platformio.ini` envs had
  already been dropped when the project pivoted to `cyd_28` + the Windows
  GUI/serial-bridge flow — this file previously still described the old
  7-board architecture as current). Fixed the two `#ifdef BOARD_CYD_28`
  leaks in `main.cpp`/`ui.cpp` into a `BoardCaps.has_pwr_button` runtime
  flag. Deduplicated ~300 lines shared between the macOS/Linux and Windows
  BLE daemons into `daemon/usage_common.py`. Removed dead root-level files
  left over from the TokenMeter→TokenDeck rebrand (`tokenmeter_gui.py`,
  orphaned `components/`, duplicate `.cmd` launchers).
- **AMOLED-1.8 chime verified on hardware + EXIO2 touch-kill fix (2026-07-13).**
  (Historical — this board's firmware source was removed above; kept for
  context if that port is ever revived from git history.) The 1.8's `amp_enable` hook drove both GPIO 46 and XCA9554 EXIO2 ("the unused one is harmless") — but pulling EXIO2 low takes the FT3168 off the I2C bus (chip stops ACKing; IDF reports it as `ESP_ERR_INVALID_STATE`, which reads like a driver wedge and cost a long I2S red-herring chase). Amp enable is GPIO 46 only; EXIO2 must stay HIGH. Chime, touch, buttons, and BLE bond persistence all verified on a real 1.8.
- **Device-abstraction refactor (2026-05-18).** All board-conditional code moved out of shared files into `boards/<name>/` and behind a HAL in `hal/`. ~30 `#ifdef BOARD_*` blocks went to zero. UI is responsive via `compute_layout()` driven by `board_caps()`. New ports add a folder + a PlatformIO env — no shared file edits.
- Added second board port: Waveshare AMOLED-1.8 (368×448 portrait, SH8601, FT3168, XCA9554 IO expander).
- Migrated from Panlee SC01 Plus (480×320 IPS) to Waveshare 2.16" AMOLED (480×480 square). Full hardware/library swap.
- Added IMU auto-rotation, battery indicator, USB-state-aware screen switching.
- Added splash screen with scraped pixel-art animations and 3-button physical input layout.
- Fonts and icons re-scaled ~1.9× for the higher-DPI panel.
- All UI margins widened to 20px to clear the rounded display corners.
- Battery icons converted to RGB565A8 alpha so they blend cleanly over the splash animations.

## Daemon / host side

**Current path (Windows, `cyd_28`):** `tokendeck_gui.py` (WebView2 GUI) plus
`daemon/usage_serial_bridge_windows.py` poll the Anthropic/Codex/Gemini APIs
and write JSON over **USB serial** to the CYD board — no BLE involved for
this hardware. See [README.md](README.md) for the current launcher scripts
(`tokendeck.cmd`, `tokendeck-server.cmd`, `tokendeck-record.cmd`).

**Legacy path (BLE, retired Waveshare hardware):** the daemons below still
work for anyone with a previously-flashed BLE-capable board (that firmware
source no longer builds from this repo — see "Project context" above), and
their shared logic lives in `daemon/usage_common.py`.

Bash daemon (`daemon/claude-usage-daemon.sh`) reads OAuth token, polls Anthropic API, sends JSON over BLE GATT. Run with `systemctl --user start claude-usage-daemon`. The unit file's `ExecStart` is the absolute path to the script — repoint it when switching between the worktree and the main checkout. `daemon/claude_usage_daemon.py` (macOS/Linux) and `daemon/claude_usage_daemon_windows.py` (Windows, run manually or via `daemon/tray_windows.py`) are the Python equivalents.

**Discovery & resilience:**

- Connects by name (`"Clawdmeter"`) on first run, caches resolved MAC at `~/.config/claude-usage-monitor/ble-address`. ESP32 BLE addresses are factory-burned per-chip, so swapping any board invalidates the cache.
- On connect failure: cache is dropped AND device is removed from bluez (`bluetoothctl remove`) so the next scan won't re-pick a dead MAC. Multi-candidate scans pick `head -1` and let the failure cycle converge.
- `POLL_INTERVAL=60`, `TICK=5`. Inner loop wakes every 5s to detect disconnects fast; polls Anthropic when 60s elapsed OR when ESP fires a refresh request.

**GATT characteristics on service `4c41555a-...0001`:**

- `...0002` RX — daemon writes JSON usage payload here.
- `...0003` TX — firmware notifies ack/nack (daemon doesn't subscribe).
- `...0004` REQ — firmware fires `0x01` notify in `onSubscribe` if `has_received_data` is false. Daemon subscribes via `setsid bash -c "stdbuf -oL dbus-monitor … | awk …"`; awk drops a flag file the inner loop picks up. See the `feedback_dbus_monitor_pipe` memory for the three subtle gotchas (pipe buffering, busctl-exits race, `wait` blocking on pipeline jobs).
