#include "../../hal/power_hal.h"
#include <Arduino.h>

// No CYD, o gesto de pareamento usa um toque longo na tela. O núcleo recebe
// o evento LONG após 1,5 s e arma o pareamento após outros 1,5 s; ao soltar
// o dedo, os vínculos antigos são limpos e o anúncio Bluetooth é reiniciado.
extern bool cyd_touch_is_pressed(void);

void power_hal_init(void) {}

void power_hal_tick(void) {}

int power_hal_battery_pct(void) { return -1; }
bool power_hal_is_charging(void) { return false; }
bool power_hal_is_vbus_in(void) { return false; }
bool power_hal_pwr_pressed(void) { return false; }

bool power_hal_pwr_long_pressed(void) { return false; }
bool power_hal_pwr_released(void) { return false; }
