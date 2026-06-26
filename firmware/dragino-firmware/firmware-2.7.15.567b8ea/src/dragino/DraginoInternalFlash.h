#pragma once

#include <stddef.h>
#include <stdint.h>

namespace dragino {
namespace internalFlash {

uint32_t pageSize();
bool isPageAligned(uint32_t address);
bool isRangeInFlash(uint32_t address, size_t size);
bool read(uint32_t address, void *buf, size_t size);
bool erasePage(uint32_t pageAddress);
bool programDoublewords(uint32_t address, const void *buf, size_t size);
bool rewritePage(uint32_t pageAddress, const uint8_t *pageData, size_t pageSize);

} // namespace internalFlash
} // namespace dragino
