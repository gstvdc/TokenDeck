#include "board.h"
#include <Arduino.h>

extern "C" void board_init(void) {
    pinMode(LCD_BL, OUTPUT);
    digitalWrite(LCD_BL, LOW);
}
