#include "ble.h"

#ifdef USE_WIFI_BRIDGE
// Wi-Fi builds do not link NimBLE. These legacy HID/pairing hooks remain in
// the shared input loop but intentionally do nothing on the CYD dashboard.
void ble_keyboard_press(uint8_t, uint8_t) {}
void ble_keyboard_release(void) {}
void ble_clear_bonds(void) {}
#endif
