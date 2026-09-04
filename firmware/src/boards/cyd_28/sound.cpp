#include "../../hal/sound_hal.h"

// O ESP32-2432S028R não possui saída de áudio usada pelo Clawdmeter.
void sound_hal_init(void) {}
void sound_hal_tick(void) {}
void sound_hal_play_reset(void) {}
