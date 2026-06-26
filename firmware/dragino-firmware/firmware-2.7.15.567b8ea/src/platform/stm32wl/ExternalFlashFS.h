/*
 * ExternalFlashFS.h
 *
 * External SPI Flash filesystem implementation for STM32WL
 * Based on LittleFS with custom SPI Flash backend
 */

#ifndef EXTERNALFLASHFS_H_
#define EXTERNALFLASHFS_H_

#include "STM32_LittleFS.h"

class ExternalFlashFS : public STM32_LittleFS
{
  public:
    ExternalFlashFS(void);

    // Initialize the external SPI Flash and mount filesystem
    bool begin(void);

    // Initialize SPI Flash hardware (should be called before begin)
    bool initFlashHardware(void);

    // Put SPI Flash into Deep Power-Down and disable SPI peripheral
    void powerDown(void);

  private:
    bool _flash_initialized;
};

// Global instance - similar to InternalFS
extern ExternalFlashFS ExternalFS;

#endif /* EXTERNALFLASHFS_H_ */
