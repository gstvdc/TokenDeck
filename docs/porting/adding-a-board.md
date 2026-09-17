# Porting the firmware to a new board

A board port is a folder under `firmware/src/boards/` plus a new
`[env:...]` block in `firmware/platformio.ini`. You should never need
to edit `firmware/src/main.cpp`, `firmware/src/ui.cpp`, or anything
under `firmware/src/hal/`. If you find yourself wanting to, that's a
gap in the HAL — open an issue.

Today the only shipping port is `cyd_28` (ESP32-2432S028R "CYD", a
classic ESP32 + ILI9341 + XPT2046, no PSRAM, no PMU/IMU). Use it as
your worked example for the HAL contract; `boards/template/` is the
TODO-scaffolded starting point.

## Hardware you need

At minimum:

- An ESP32 (classic, S2, S3, or C6 — the HAL has no ESP32-family
  assumptions baked in; PSRAM is optional, gated by `BOARD_HAS_PSRAM`).
- A panel with a driver supported by
  [GFX Library for Arduino](https://github.com/moononournation/Arduino_GFX)
  (SPI, QSPI, or RGB parallel).
- A **touch controller** over I2C or SPI. The HAL just needs init + read;
  you can use any driver you can compile.
- A **primary button** (typically the BOOT/GPIO 0 push button).

Optional:

- A second physical button (e.g. for HID Shift+Tab mode toggle).
- A PMU for battery monitoring + a power button (set
  `BOARD_HAS_PWR_BUTTON` accordingly — see `hal/board_caps.h`).
- An IMU for automatic rotation.
- An IO expander if reset / enable lines are routed through one.

## Step-by-step

1. **Copy the template folder.**

   ```bash
   cp -r firmware/src/boards/template firmware/src/boards/my_board
   ```

2. **Fill in `boards/my_board/board.h`.** Replace every `TODO` with your
   board's pins, I2C addresses, dimensions, and capability flags. The
   capability flags drive both compile-time dead-stripping in the HAL
   implementations and runtime UI decisions via `BoardCaps`.

3. **Implement the per-board sources.** Each one corresponds to a HAL
   header in `firmware/src/hal/`: `display.cpp`, `touch.cpp`,
   `input.cpp`, `power.cpp`, `imu.cpp`, `caps.cpp`, `board_init.cpp`.
   `boards/cyd_28/` is the current reference implementation for all of
   them; `boards/template/` documents what each file needs to provide
   even when a feature (PMU, IMU, IO expander) is absent.

4. **Add a PlatformIO env.** In `firmware/platformio.ini`, copy the
   `[env:cyd_28]` block and adjust:

   ```ini
   [env:my_board]
   ; ... platform / board / framework as before ...

   build_src_filter =
       +<*>
       -<boards/>
       +<boards/my_board/>          ; the only line you change here

   build_flags =
       -DBOARD_MY_BOARD             ; identity-only — the shared code never
                                     ; branches on this; per-board code may
   ```

   Also drop `-<chime.cpp> -<es8311.c>` from the filter, and the LVGL
   `build_flags` trimmed for a small no-PSRAM panel, if they don't apply
   to your board.

5. **Build.** `pio run -d firmware -e my_board`. The link step is the
   real verification — any missing HAL symbol or duplicated definition
   shows up here.

6. **Flash + smoke test.** The first boot should land on the splash
   screen. If it doesn't, check `pio device monitor` for HAL init
   messages — the reference port logs OK / failure for display, touch,
   and power during `setup()`.

7. **Visual QA.** Eyeball the display on real hardware — the LVGL
   framebuffer-snapshot tooling was removed since it needed
   `LV_USE_SNAPSHOT`, which `cyd_28` (no PSRAM) builds with off. The UI
   is responsive (see [hal-contract.md](hal-contract.md) for breakpoint
   details); most ports will look acceptable out of the box. If your
   screen size doesn't match an existing breakpoint, you may want to add
   one to
   `compute_layout()` in `firmware/src/ui.cpp`.

## Common pitfalls

- **Display stays black, no panic.** Usually one of: PSRAM expected but
  not enabled (only relevant if `BOARD_HAS_PSRAM` is set — check
  `board_build.arduino.memory_type = qio_opi` for QSPI panels that need
  it); IO expander not released before `gfx->begin()` (run
  `io_expander_init()` from `board_init()`); GFX library version too old
  to know about your panel chip; reset line not pulsed before
  `gfx->begin()` (do it in `board_init()` for direct-GPIO resets, or via
  the IO expander otherwise).
- **Touch reads zeros / wrong coordinates.** The HAL hands LVGL whatever
  the controller reports — apply any axis swap / mirror / calibration
  bounds inside your `touch.cpp` (see `TOUCH_MIN_X`/`MAX_X`/... in
  `boards/cyd_28/board.h` for a resistive-touch calibration example).
- **GPL warning when picking a touch driver.** The project intentionally
  avoids copyleft dependencies. If the only available library is GPL,
  vendor a minimal reader instead.
- **Both boards built fine but one runs and the other doesn't.** The
  build_src_filter is per-env — re-check you copied the existing env
  block correctly and the `-<boards/>` then `+<boards/your_one/>`
  ordering is right (filters apply in declaration order).
