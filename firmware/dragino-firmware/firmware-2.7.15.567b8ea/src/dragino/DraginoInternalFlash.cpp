#include "DraginoInternalFlash.h"

#include "configuration.h"
#include <string.h>

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32) && defined(ARCH_STM32WL)
#include "stm32wlxx_hal_flash.h"
#define DRAGINO_INTERNAL_FLASH_AVAILABLE 1
#endif

namespace dragino {
namespace internalFlash {

uint32_t pageSize()
{
#if defined(DRAGINO_INTERNAL_FLASH_AVAILABLE)
    return FLASH_PAGE_SIZE;
#else
    return 0;
#endif
}

bool isPageAligned(uint32_t address)
{
#if defined(DRAGINO_INTERNAL_FLASH_AVAILABLE)
    return (address % FLASH_PAGE_SIZE) == 0;
#else
    (void)address;
    return false;
#endif
}

bool isRangeInFlash(uint32_t address, size_t size)
{
#if defined(DRAGINO_INTERNAL_FLASH_AVAILABLE)
    if (size == 0) {
        return true;
    }

    const uint32_t start = FLASH_BASE;
    const uint32_t endInclusive = FLASH_END_ADDR;
    const uint32_t last = address + static_cast<uint32_t>(size - 1U);

    return address >= start && last >= address && last <= endInclusive;
#else
    (void)address;
    (void)size;
    return false;
#endif
}

bool read(uint32_t address, void *buf, size_t size)
{
    if (!buf) {
        return false;
    }

#if defined(DRAGINO_INTERNAL_FLASH_AVAILABLE)
    if (!isRangeInFlash(address, size)) {
        LOG_WARN("InternalFlash: read out of range addr=0x%08x size=%u", (unsigned)address, (unsigned)size);
        return false;
    }

    memcpy(buf, reinterpret_cast<const void *>(address), size);
    return true;
#else
    (void)address;
    (void)size;
    return false;
#endif
}

bool erasePage(uint32_t pageAddress)
{
#if defined(DRAGINO_INTERNAL_FLASH_AVAILABLE)
    if (!isPageAligned(pageAddress)) {
        LOG_WARN("InternalFlash: erase address is not page aligned: 0x%08x", (unsigned)pageAddress);
        return false;
    }
    if (!isRangeInFlash(pageAddress, FLASH_PAGE_SIZE)) {
        LOG_WARN("InternalFlash: erase out of range addr=0x%08x", (unsigned)pageAddress);
        return false;
    }

    FLASH_EraseInitTypeDef erase = {};
    erase.TypeErase = FLASH_TYPEERASE_PAGES;
    erase.Page = (pageAddress - FLASH_BASE) / FLASH_PAGE_SIZE;
    erase.NbPages = 1;

    uint32_t pageError = 0;
    if (HAL_FLASH_Unlock() != HAL_OK) {
        LOG_WARN("InternalFlash: unlock failed before erase");
        return false;
    }

    const HAL_StatusTypeDef status = HAL_FLASHEx_Erase(&erase, &pageError);
    HAL_FLASH_Lock();

    if (status != HAL_OK) {
        LOG_WARN("InternalFlash: erase failed page=%u error=0x%08x",
                 (unsigned)erase.Page,
                 (unsigned)HAL_FLASH_GetError());
        return false;
    }

    return true;
#else
    (void)pageAddress;
    return false;
#endif
}

bool programDoublewords(uint32_t address, const void *buf, size_t size)
{
    if (!buf) {
        return false;
    }

#if defined(DRAGINO_INTERNAL_FLASH_AVAILABLE)
    if ((address % sizeof(uint64_t)) != 0 || (size % sizeof(uint64_t)) != 0) {
        LOG_WARN("InternalFlash: program must be doubleword aligned addr=0x%08x size=%u",
                 (unsigned)address,
                 (unsigned)size);
        return false;
    }
    if (!isRangeInFlash(address, size)) {
        LOG_WARN("InternalFlash: program out of range addr=0x%08x size=%u", (unsigned)address, (unsigned)size);
        return false;
    }

    const uint8_t *bytes = static_cast<const uint8_t *>(buf);

    if (HAL_FLASH_Unlock() != HAL_OK) {
        LOG_WARN("InternalFlash: unlock failed before program");
        return false;
    }

    HAL_StatusTypeDef status = HAL_OK;
    for (size_t offset = 0; offset < size; offset += sizeof(uint64_t)) {
        uint64_t word = 0;
        memcpy(&word, bytes + offset, sizeof(word));
        if (word == 0xFFFFFFFFFFFFFFFFULL) {
            continue;
        }
        status = HAL_FLASH_Program(FLASH_TYPEPROGRAM_DOUBLEWORD, address + static_cast<uint32_t>(offset), word);
        if (status != HAL_OK) {
            break;
        }
    }

    HAL_FLASH_Lock();

    if (status != HAL_OK) {
        LOG_WARN("InternalFlash: program failed addr=0x%08x error=0x%08x",
                 (unsigned)address,
                 (unsigned)HAL_FLASH_GetError());
        return false;
    }

    return memcmp(reinterpret_cast<const void *>(address), buf, size) == 0;
#else
    (void)address;
    (void)size;
    return false;
#endif
}

bool rewritePage(uint32_t pageAddress, const uint8_t *pageData, size_t pageSize)
{
    if (!pageData) {
        return false;
    }

#if defined(DRAGINO_INTERNAL_FLASH_AVAILABLE)
    if (pageSize != FLASH_PAGE_SIZE) {
        LOG_WARN("InternalFlash: rewrite size must be one page, size=%u", (unsigned)pageSize);
        return false;
    }

    if (!erasePage(pageAddress)) {
        return false;
    }

    return programDoublewords(pageAddress, pageData, pageSize);
#else
    (void)pageAddress;
    (void)pageSize;
    return false;
#endif
}

} // namespace internalFlash
} // namespace dragino
