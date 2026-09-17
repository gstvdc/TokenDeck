#include "../../hal/imu_hal.h"

// No IMU on this template. If your board ships an accelerometer (e.g.
// QMI8658) and you want auto-rotation, set BOARD_HAS_ROTATION=1 in board.h
// and implement the stubs below; a worked example (QMI8658 over I2C) is in
// git history on the retired waveshare_amoled_216 port — see CLAUDE.md's
// "Project context" section for how to find it.

void    imu_hal_init(void) {}
void    imu_hal_tick(void) {}
uint8_t imu_hal_rotation_quadrant(void) { return 0; }
