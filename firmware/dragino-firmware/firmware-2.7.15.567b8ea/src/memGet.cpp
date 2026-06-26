/**
 * @file memGet.cpp
 * @brief Implementation of MemGet class that provides functions to get memory information.
 *
 * This file contains the implementation of MemGet class that provides functions to get
 * information about free heap, heap size, free psram and psram size. The functions are
 * implemented for ESP32 and NRF52 architectures. If the platform does not have heap
 * management function implemented, the functions return UINT32_MAX or 0.
 */
#include "memGet.h"
#include "configuration.h"

#ifdef ARCH_STM32WL
#include <malloc.h>

#ifndef STM32WL_USE_EXTENDED_FREE_HEAP
#define STM32WL_USE_EXTENDED_FREE_HEAP 1
#endif

#if STM32WL_USE_EXTENDED_FREE_HEAP
extern "C" char *_sbrk(int incr);
extern "C" char _end;
extern "C" char _estack;
extern "C" char _Min_Stack_Size;

static uint32_t getStm32wlHeapLimit()
{
    return (uint32_t)&_estack - (uint32_t)&_Min_Stack_Size;
}

static uint32_t getStm32wlUnallocatedHeap()
{
    char *heapEnd = _sbrk(0);
    uint32_t heapEndAddr = (uint32_t)heapEnd;
    uint32_t heapLimit = getStm32wlHeapLimit();

    return heapEndAddr < heapLimit ? heapLimit - heapEndAddr : 0;
}
#endif
#endif

MemGet memGet;

/**
 * Returns the amount of free heap memory in bytes.
 * @return uint32_t The amount of free heap memory in bytes.
 */
uint32_t MemGet::getFreeHeap()
{
#ifdef ARCH_ESP32
    return ESP.getFreeHeap();
#elif defined(ARCH_NRF52)
    return dbgHeapFree();
#elif defined(ARCH_RP2040)
    return rp2040.getFreeHeap();
#elif defined(ARCH_STM32WL)
    struct mallinfo m = mallinfo();
#if STM32WL_USE_EXTENDED_FREE_HEAP
    return (uint32_t)m.fordblks + getStm32wlUnallocatedHeap();
#else
    return m.fordblks; // Total free space (bytes)
#endif
#else
    // this platform does not have heap management function implemented
    return UINT32_MAX;
#endif
}

/**
 * Returns the size of the heap memory in bytes.
 * @return uint32_t The size of the heap memory in bytes.
 */
uint32_t MemGet::getHeapSize()
{
#ifdef ARCH_ESP32
    return ESP.getHeapSize();
#elif defined(ARCH_NRF52)
    return dbgHeapTotal();
#elif defined(ARCH_RP2040)
    return rp2040.getTotalHeap();
#elif defined(ARCH_STM32WL)
#if STM32WL_USE_EXTENDED_FREE_HEAP
    uint32_t heapStart = (uint32_t)&_end;
    uint32_t heapLimit = getStm32wlHeapLimit();

    return heapStart < heapLimit ? heapLimit - heapStart : 0;
#else
    struct mallinfo m = mallinfo();
    return m.arena; // Non-mmapped space allocated (bytes)
#endif
#else
    // this platform does not have heap management function implemented
    return UINT32_MAX;
#endif
}

/**
 * Returns the amount of free psram memory in bytes.
 *
 * @return The amount of free psram memory in bytes.
 */
uint32_t MemGet::getFreePsram()
{
#ifdef ARCH_ESP32
    return ESP.getFreePsram();
#elif defined(ARCH_PORTDUINO)
    return 4194252;
#else
    return 0;
#endif
}

/**
 * @brief Returns the size of the PSRAM memory.
 *
 * @return uint32_t The size of the PSRAM memory.
 */
uint32_t MemGet::getPsramSize()
{
#ifdef ARCH_ESP32
    return ESP.getPsramSize();
#elif defined(ARCH_PORTDUINO)
    return 4194252;
#else
    return 0;
#endif
}

void displayPercentHeapFree()
{
    uint32_t freeHeap = memGet.getFreeHeap();
    uint32_t totalHeap = memGet.getHeapSize();
    if (totalHeap == 0 || totalHeap == UINT32_MAX) {
        LOG_INFO("Heap size unavailable");
        return;
    }
    int percent = (int)((freeHeap * 100) / totalHeap);
    LOG_INFO("Heap free: %d%% (%u/%u bytes)", percent, freeHeap, totalHeap);
}
