#include "../../hal/touch_hal.h"
#include "board.h"
#include <Arduino.h>
#include <SPI.h>

static SPIClass touch_spi(HSPI);
static volatile bool touch_down = false;

bool cyd_touch_is_pressed(void) {
    return touch_down;
}

static uint16_t read_axis(uint8_t command) {
    touch_spi.transfer(command);
    uint16_t value = (uint16_t)touch_spi.transfer(0x00) << 8;
    value |= touch_spi.transfer(0x00);
    return value >> 3;
}

static uint16_t scale_axis(uint16_t raw, uint16_t raw_min, uint16_t raw_max,
                           uint16_t screen_max) {
    long value = map(raw, raw_min, raw_max, 0, screen_max - 1);
    return (uint16_t)constrain(value, 0L, (long)screen_max - 1);
}

void touch_hal_init(void) {
    pinMode(TP_CS, OUTPUT);
    digitalWrite(TP_CS, HIGH);
    pinMode(TP_INT, INPUT_PULLUP);
    touch_spi.begin(TP_SCLK, TP_MISO, TP_MOSI, TP_CS);
}

void touch_hal_read(uint16_t* x, uint16_t* y, bool* pressed) {
    if (digitalRead(TP_INT) != LOW) {
        touch_down = false;
        *pressed = false;
        return;
    }

    touch_spi.beginTransaction(SPISettings(2000000, MSBFIRST, SPI_MODE0));
    digitalWrite(TP_CS, LOW);
    read_axis(0xD0);
    uint16_t raw_x = read_axis(0xD0);
    uint16_t raw_y = read_axis(0x90);
    digitalWrite(TP_CS, HIGH);
    touch_spi.endTransaction();

    *x = scale_axis(raw_x, TOUCH_MIN_X, TOUCH_MAX_X, LCD_WIDTH);
    *y = scale_axis(raw_y, TOUCH_MIN_Y, TOUCH_MAX_Y, LCD_HEIGHT);
    touch_down = true;
    *pressed = true;
}
