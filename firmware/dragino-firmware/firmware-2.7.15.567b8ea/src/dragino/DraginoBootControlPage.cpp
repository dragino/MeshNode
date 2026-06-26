#include "DraginoBootControlPage.h"

#include "DraginoInternalFlash.h"
#include "configuration.h"
#include <string.h>

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32) && defined(ARCH_STM32WL)
#define DRAGINO_BOOT_CONTROL_PAGE_AVAILABLE 1
#endif

namespace dragino {
namespace {

#if defined(DRAGINO_BOOT_CONTROL_PAGE_AVAILABLE)
uint8_t pageBuffer[DRAGINO_BOOT_CTRL_PAGE_SIZE];
#endif

uint32_t readU32(const uint8_t *buf, uint32_t offset)
{
    uint32_t value = 0;
    memcpy(&value, buf + offset, sizeof(value));
    return value;
}

void writeU32(uint8_t *buf, uint32_t offset, uint32_t value)
{
    memcpy(buf + offset, &value, sizeof(value));
}

bool loadPage()
{
#if defined(DRAGINO_BOOT_CONTROL_PAGE_AVAILABLE)
    return internalFlash::read(DRAGINO_BOOT_CTRL_PAGE_ADDR, pageBuffer, sizeof(pageBuffer));
#else
    return false;
#endif
}

bool rewriteLoadedPage()
{
#if defined(DRAGINO_BOOT_CONTROL_PAGE_AVAILABLE)
    return internalFlash::rewritePage(DRAGINO_BOOT_CTRL_PAGE_ADDR, pageBuffer, sizeof(pageBuffer));
#else
    return false;
#endif
}

} // namespace

uint32_t readBootControlAppVersion()
{
#if defined(DRAGINO_BOOT_CONTROL_PAGE_AVAILABLE)
    uint32_t version = 0xFFFFFFFFUL;
    if (!internalFlash::read(DRAGINO_BOOT_CTRL_PAGE_ADDR + DRAGINO_APP_VERSION_OFFSET, &version, sizeof(version))) {
        return 0xFFFFFFFFUL;
    }
    return version;
#else
    return 0xFFFFFFFFUL;
#endif
}

bool hasBootloaderUpgradeRequest()
{
#if defined(DRAGINO_BOOT_CONTROL_PAGE_AVAILABLE)
    uint32_t magic = 0xFFFFFFFFUL;
    if (!internalFlash::read(DRAGINO_BOOT_CTRL_PAGE_ADDR + DRAGINO_BOOT_REQ_MAGIC_OFFSET, &magic, sizeof(magic))) {
        return false;
    }
    return magic == DRAGINO_BOOT_REQ_MAGIC_ENTER;
#else
    return false;
#endif
}

bool requestBootloaderUpgrade(BootUpgradeReason reason)
{
#if defined(DRAGINO_BOOT_CONTROL_PAGE_AVAILABLE)
    if (!loadPage()) {
        LOG_WARN("BootControl: failed to read control page before request");
        return false;
    }

    uint32_t counter = readU32(pageBuffer, DRAGINO_BOOT_REQ_COUNTER_OFFSET);
    if (counter == 0xFFFFFFFFUL) {
        counter = 0;
    }

    writeU32(pageBuffer, DRAGINO_BOOT_REQ_MAGIC_OFFSET, DRAGINO_BOOT_REQ_MAGIC_ENTER);
    writeU32(pageBuffer, DRAGINO_BOOT_REQ_REASON_OFFSET, static_cast<uint32_t>(reason));
    writeU32(pageBuffer, DRAGINO_BOOT_REQ_COUNTER_OFFSET, counter + 1U);
    writeU32(pageBuffer, DRAGINO_BOOT_REQ_CRC_OFFSET, 0U);

    if (!rewriteLoadedPage()) {
        LOG_WARN("BootControl: failed to write upgrade request");
        return false;
    }

    LOG_INFO("BootControl: upgrade request set reason=%u counter=%u",
             (unsigned)static_cast<uint32_t>(reason),
             (unsigned)(counter + 1U));
    return true;
#else
    (void)reason;
    return false;
#endif
}

bool clearBootloaderUpgradeRequest()
{
#if defined(DRAGINO_BOOT_CONTROL_PAGE_AVAILABLE)
    if (!hasBootloaderUpgradeRequest()) {
        return true;
    }

    if (!loadPage()) {
        LOG_WARN("BootControl: failed to read control page before clear");
        return false;
    }

    writeU32(pageBuffer, DRAGINO_BOOT_REQ_MAGIC_OFFSET, DRAGINO_BOOT_REQ_MAGIC_EMPTY);
    writeU32(pageBuffer, DRAGINO_BOOT_REQ_REASON_OFFSET, 0U);
    writeU32(pageBuffer, DRAGINO_BOOT_REQ_CRC_OFFSET, 0U);

    if (!rewriteLoadedPage()) {
        LOG_WARN("BootControl: failed to clear upgrade request");
        return false;
    }

    LOG_INFO("BootControl: stale upgrade request cleared");
    return true;
#else
    return true;
#endif
}

bool ensureBootloaderWillJumpAppOnNormalReset()
{
#if defined(DRAGINO_BOOT_CONTROL_PAGE_AVAILABLE)
    if (!hasBootloaderUpgradeRequest()) {
        return true;
    }

    LOG_WARN("BootControl: upgrade request present on normal reset path, clearing");
    return clearBootloaderUpgradeRequest();
#else
    return true;
#endif
}

} // namespace dragino
