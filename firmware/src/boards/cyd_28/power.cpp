#include "../../hal/power_hal.h"
#include <Arduino.h>

// cyd_28 has no PWR key and talks to the host over USB serial, not BLE — see
// CLAUDE.md's "Hardware (critical pins)" section. There is no pairing
// gesture on this board; pair_tick() in main.cpp is compiled out entirely
// under USE_USB_SERIAL_BRIDGE, which this board's env always defines. These
// stubs exist only to satisfy the power_hal contract.

void power_hal_init(void) {}

void power_hal_tick(void) {}

int power_hal_battery_pct(void) { return -1; }
bool power_hal_is_charging(void) { return false; }
bool power_hal_is_vbus_in(void) { return false; }
bool power_hal_pwr_pressed(void) { return false; }

bool power_hal_pwr_long_pressed(void) { return false; }
bool power_hal_pwr_released(void) { return false; }
