#include "ble.h"

#if defined(USE_WIFI_BRIDGE) || defined(USE_USB_SERIAL_BRIDGE)
// Wi-Fi and USB builds do not link NimBLE. These legacy HID/pairing hooks remain in
// the shared input loop but intentionally do nothing on the CYD dashboard.
void ble_keyboard_press(uint8_t, uint8_t) {}
void ble_keyboard_release(void) {}
void ble_clear_bonds(void) {}
#endif
