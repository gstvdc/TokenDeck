#include "../../hal/display_hal.h"
#include "board.h"
#include <Arduino.h>
#include <Arduino_GFX_Library.h>

static Arduino_DataBus* bus = nullptr;
static Arduino_ILI9341* gfx = nullptr;

void display_hal_init(void) {
    bus = new Arduino_ESP32SPI(LCD_DC, LCD_CS, LCD_SCLK, LCD_MOSI, LCD_MISO);
    gfx = new Arduino_ILI9341(bus, LCD_RST, 1 /* landscape */, false /* IPS */);
}

void display_hal_begin(void) {
    if (!gfx) return;
    gfx->begin(40000000);
    gfx->fillScreen(0x0000);
    ledcSetup(0, 5000, 8);
    ledcAttachPin(LCD_BL, 0);
    ledcWrite(0, 200);
}

void display_hal_set_brightness(uint8_t level) {
    ledcWrite(0, level);
}

void display_hal_fill_screen(uint16_t color) {
    if (gfx) gfx->fillScreen(color);
}

void display_hal_draw_bitmap(int32_t x, int32_t y, int32_t w, int32_t h,
                             const uint16_t* pixels) {
    if (gfx) gfx->draw16bitRGBBitmap(x, y, const_cast<uint16_t*>(pixels), w, h);
}

void display_hal_tick(void) {}

void display_hal_round_area(int32_t* x1, int32_t* y1, int32_t* x2, int32_t* y2) {
    (void)x1; (void)y1; (void)x2; (void)y2;
}
