#include "wifi_bridge.h"

#ifdef USE_WIFI_BRIDGE
#include <WiFi.h>
#include <HTTPClient.h>
#include "wifi_config.generated.h"

static String pending[2];
static uint8_t pending_count = 0;
static uint32_t last_poll_ms = 0;
static uint32_t last_connect_attempt_ms = 0;

static void wifi_event(WiFiEvent_t event, WiFiEventInfo_t info) {
    if (event == ARDUINO_EVENT_WIFI_STA_GOT_IP) {
        Serial.printf("WiFi: connected, IP=%s\n", WiFi.localIP().toString().c_str());
    } else if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
        Serial.printf("WiFi: disconnected, reason=%u\n",
                      info.wifi_sta_disconnected.reason);
    }
}

static void connect_wifi(void) {
    last_connect_attempt_ms = millis();
    WiFi.mode(WIFI_STA);
    WiFi.setHostname(DEVICE_NAME);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.printf("WiFi: connecting to %s\n", WIFI_SSID);
}

static void fetch(const char* url) {
    if (pending_count >= 2 || !url || !*url) return;
    HTTPClient http;
    http.setConnectTimeout(2500);
    http.setTimeout(3000);
    if (!http.begin(url)) return;
    const int status = http.GET();
    if (status == HTTP_CODE_OK) {
        pending[pending_count++] = http.getString();
    } else {
        Serial.printf("Bridge GET %s -> %d\n", url, status);
    }
    http.end();
}

void wifi_bridge_init(void) {
    WiFi.persistent(false);
    WiFi.setAutoReconnect(true);
    WiFi.onEvent(wifi_event);

    const int networks = WiFi.scanNetworks();
    bool target_found = false;
    for (int i = 0; i < networks; ++i) {
        if (WiFi.SSID(i) == WIFI_SSID) {
            target_found = true;
            Serial.printf("WiFi: target found, RSSI=%d dBm, encryption=%u\n",
                          WiFi.RSSI(i), WiFi.encryptionType(i));
            break;
        }
    }
    if (!target_found) Serial.println("WiFi: target network not found");
    WiFi.scanDelete();
    connect_wifi();
}

void wifi_bridge_reconnect(void) {
    WiFi.disconnect();
    connect_wifi();
}

bool wifi_bridge_is_connected(void) {
    return WiFi.status() == WL_CONNECTED;
}

void wifi_bridge_tick(void) {
    if (!wifi_bridge_is_connected()) {
        if (millis() - last_connect_attempt_ms >= 10000) connect_wifi();
        return;
    }
    if (pending_count || millis() - last_poll_ms < REFRESH_INTERVAL_MS) return;
    last_poll_ms = millis();
#if USE_CODEX
    fetch(CODEX_BRIDGE_URL);
#endif
#if USE_CLAUDE
    fetch(CLAUDE_BRIDGE_URL);
#endif
}

bool wifi_bridge_pop(String& json) {
    if (!pending_count) return false;
    json = pending[0];
    if (pending_count > 1) pending[0] = pending[1];
    pending[--pending_count] = "";
    return true;
}
#else
void wifi_bridge_init(void) {}
void wifi_bridge_tick(void) {}
void wifi_bridge_reconnect(void) {}
bool wifi_bridge_is_connected(void) { return false; }
bool wifi_bridge_pop(String&) { return false; }
#endif
