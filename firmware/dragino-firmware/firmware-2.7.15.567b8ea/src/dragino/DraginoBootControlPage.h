#pragma once

#include <stdint.h>

namespace dragino {

constexpr uint32_t DRAGINO_BOOT_CTRL_PAGE_ADDR = 0x0803F000UL;
constexpr uint32_t DRAGINO_BOOT_CTRL_PAGE_SIZE = 0x800UL;

constexpr uint32_t DRAGINO_APP_VERSION_OFFSET = 0x00UL;
constexpr uint32_t DRAGINO_BOOT_REQ_MAGIC_OFFSET = 0x20UL;
constexpr uint32_t DRAGINO_BOOT_REQ_REASON_OFFSET = 0x24UL;
constexpr uint32_t DRAGINO_BOOT_REQ_COUNTER_OFFSET = 0x28UL;
constexpr uint32_t DRAGINO_BOOT_REQ_CRC_OFFSET = 0x2CUL;

constexpr uint32_t DRAGINO_BOOT_REQ_MAGIC_ENTER = 0x424F4F54UL; // "BOOT"
constexpr uint32_t DRAGINO_BOOT_REQ_MAGIC_EMPTY = 0xFFFFFFFFUL;

enum class BootUpgradeReason : uint32_t {
    Unknown = 0,
    SerialUart = 1,
    Bluetooth = 2,
    UpperComputer = 3,
    Test = 4,
};

bool requestBootloaderUpgrade(BootUpgradeReason reason);
bool clearBootloaderUpgradeRequest();
bool hasBootloaderUpgradeRequest();
bool ensureBootloaderWillJumpAppOnNormalReset();
uint32_t readBootControlAppVersion();

} // namespace dragino
