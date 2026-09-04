#pragma once

// ESP32-2432S028R (CYD 2.8"): ESP32 clássico, ILI9341 e XPT2046.
#define BOARD_NAME "CYD 2.8"

#define LCD_WIDTH  320
#define LCD_HEIGHT 240

#define LCD_MISO 12
#define LCD_MOSI 13
#define LCD_SCLK 14
#define LCD_CS   15
#define LCD_DC   2
#define LCD_RST  -1
#define LCD_BL   21

#define TP_SCLK 25
#define TP_MOSI 32
#define TP_MISO 39
#define TP_CS   33
#define TP_INT  36

#define TOUCH_MIN_X 540
#define TOUCH_MAX_X 3640
#define TOUCH_MIN_Y 700
#define TOUCH_MAX_Y 3490

#define BTN_BACK_GPIO 0

#define BOARD_HAS_SECONDARY_BUTTON 0
#define BOARD_HAS_ROTATION         0
#define BOARD_HAS_IMU              0
#define BOARD_HAS_BATTERY          0
#define BOARD_HAS_IO_EXPANDER      0
#define BOARD_HAS_SOUND            0
