#pragma once

#include <stdint.h>

#ifndef DRAGINO_STM32_IWDG_ENABLE
#define DRAGINO_STM32_IWDG_ENABLE 0
#endif

#ifndef DRAGINO_STM32_IWDG_TIMEOUT_US
#define DRAGINO_STM32_IWDG_TIMEOUT_US 32000000UL
#endif

#ifndef DRAGINO_STM32_IWDG_FEED_INTERVAL_MS
#define DRAGINO_STM32_IWDG_FEED_INTERVAL_MS 10000UL
#endif

#define DRAGINO_STM32_IWDG_SLEEP_FREEZE 1
#define DRAGINO_STM32_IWDG_SLEEP_SLICED_FEED 2

#ifndef DRAGINO_STM32_IWDG_SLEEP_MODE
#define DRAGINO_STM32_IWDG_SLEEP_MODE DRAGINO_STM32_IWDG_SLEEP_FREEZE
#endif

#ifndef DRAGINO_STM32_IWDG_BOOTLOADER_HANDOFF
#define DRAGINO_STM32_IWDG_BOOTLOADER_HANDOFF 0
#endif

#ifndef DRAGINO_STM32_IWDG_AUTO_CONFIG_OPTION_BYTES
#define DRAGINO_STM32_IWDG_AUTO_CONFIG_OPTION_BYTES 0
#endif

namespace dragino {
namespace watchdog {

bool enabled();
bool wasReset();
void beginEarly();
void feed();
void feedNow();
void prepareForSleep();
void afterStopWake();
bool stopFreezeOptionBytesOk();

} // namespace watchdog
} // namespace dragino
