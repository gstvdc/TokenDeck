#pragma once
#include <stdint.h>

// User-controlled display brightness, persisted to NVS.
void    brightness_init(void);         // load saved level from NVS and apply
void    brightness_cycle(void);        // advance to next preset level, save, apply
void    brightness_set(uint8_t level); // set explicit PWM level (5..255), save, apply
uint8_t brightness_get(void);          // current PWM level (0..255)
