#pragma once

#include <Arduino.h>

void wifi_bridge_init(void);
void wifi_bridge_tick(void);
void wifi_bridge_reconnect(void);
bool wifi_bridge_is_connected(void);
bool wifi_bridge_pop(String& json);
