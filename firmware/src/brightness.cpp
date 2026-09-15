#include "brightness.h"
#include "idle.h"
#include <Preferences.h>
#include <Arduino.h>

// Four-step ramp. The default (index 2) is 200 — identical to the prior
// hard-coded DISPLAY_DEFAULT_BRIGHTNESS, so cycling is purely additive.
static const uint8_t LEVELS[] = {64, 128, 200, 255};
#define LEVELS_COUNT (sizeof(LEVELS) / sizeof(LEVELS[0]))
#define DEFAULT_IDX  2

static uint8_t cur_idx = DEFAULT_IDX;
static uint8_t cur_level = LEVELS[DEFAULT_IDX];

void brightness_init(void) {
    Preferences prefs;
    prefs.begin("clawdmeter", true);
    uint8_t saved_val = prefs.getUChar("brt_val", 0xFF);
    uint8_t saved_idx = prefs.getUChar("brt_idx", 0xFF);
    prefs.end();

    if (saved_val >= 5 && saved_val <= 255) {
        cur_level = saved_val;
    } else if (saved_idx < LEVELS_COUNT) {
        cur_idx = saved_idx;
        cur_level = LEVELS[cur_idx];
    } else {
        cur_level = LEVELS[DEFAULT_IDX];
    }
    idle_set_awake_brightness(cur_level);
    Serial.printf("Brightness init: level=%u\n", cur_level);
}

void brightness_set(uint8_t level) {
    if (level < 5 && level > 0) level = 5;
    cur_level = level;

    Preferences prefs;
    prefs.begin("clawdmeter", false);
    prefs.putUChar("brt_val", cur_level);
    prefs.end();

    idle_set_awake_brightness(cur_level);
    Serial.printf("{\"brightness\":%u}\n", cur_level);
}

void brightness_cycle(void) {
    cur_idx = (cur_idx + 1) % LEVELS_COUNT;
    cur_level = LEVELS[cur_idx];

    Preferences prefs;
    prefs.begin("clawdmeter", false);
    prefs.putUChar("brt_idx", cur_idx);
    prefs.putUChar("brt_val", cur_level);
    prefs.end();

    idle_set_awake_brightness(cur_level);
    Serial.printf("Brightness cycled: level=%u (idx=%u)\n", cur_level, cur_idx);
}

uint8_t brightness_get(void) {
    return cur_level;
}
