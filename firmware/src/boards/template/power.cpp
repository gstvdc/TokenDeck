#include "../../hal/power_hal.h"
#include "board.h"
#include <Arduino.h>

// Minimal stub — replace with real power management for your board.
//
// If your board has an AXP2101 or similar PMU, or a PWR button wired
// through an IO expander rather than the PMU's PKEY pin, worked examples
// (waveshare_amoled_216 / waveshare_amoled_18) are in git history — see
// CLAUDE.md's "Project context" section for how to find them.
//
// If your board has no PMU and no PWR button, leave the stubs as below
// and set BOARD_HAS_BATTERY=0 in board.h — the UI honors caps.has_battery
// and hides the battery indicator.

void power_hal_init(void) {}
void power_hal_tick(void) {}

int  power_hal_battery_pct(void) { return -1; }
bool power_hal_is_charging(void) { return false; }
bool power_hal_is_vbus_in(void)  { return false; }
bool power_hal_pwr_pressed(void) { return false; }
// Hold-to-pair gesture signals. Mirror the 216 (PMU PKEY long/positive IRQs)
// or the 1.8" (software hold-timing off a polled GPIO) port. Stub = no gesture.
bool power_hal_pwr_long_pressed(void) { return false; }
bool power_hal_pwr_released(void) { return false; }
