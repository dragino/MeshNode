/*
 * ExternalFlashFS.cpp
 *
 * External SPI Flash filesystem implementation for STM32WL
 * Based on LittleFS with custom SPI Flash backend
 *
 * Supports common SPI Flash chips: W25Q series, MX25L series, etc.
 */

#include "ExternalFlashFS.h"
#include <Arduino.h>
#include <SPI.h>

/**********************************************************************************************************************
 * Macro definitions and Configuration
 **********************************************************************************************************************/
#define LFS_UNUSED(p) (void)((p))

// SPI Flash Configuration - ZB25VQ32 (Zbit, 4MB, SPI1 on PA5/PA6/PA7, CS on PA4)
// Reference: zb25vq32.h / zb25vq32.c in src/platform/stm32wl/reference/
#define EXT_FLASH_SPI_FREQUENCY 4000000    // 4MHz - safe for ZB25VQ32 (max 104MHz)
#define EXT_FLASH_PAGE_SIZE     256U       // ZB25VQ32: 16384 pages x 256 bytes
#define EXT_FLASH_SECTOR_SIZE   4096U      // ZB25VQ32: 1024 sectors x 4KB
#define EXT_FLASH_TOTAL_SIZE    (4U * 1024U * 1024U)  // ZB25VQ32: 32Mbit = 4MB
#define EXT_FLASH_BLOCK_SIZE    4096U      // LittleFS block size = sector size

// ZB25VQ32 JEDEC ID: Manufacturer=0x5E, MemType=0x40, Capacity=0x16
#define ZB25VQ32_JEDEC_ID       0x5E4016U

// ZB25VQ32 worst-case timing (from datasheet via reference driver)
#define EXT_FLASH_T_PAGE_PROG_MS   3U    // Page program max: 3ms
#define EXT_FLASH_T_SECTOR_ERASE_MS 200U // Sector (4K) erase max: 200ms
#define EXT_FLASH_T_BLOCK_ERASE_MS 2000U // Block (64K) erase max: 2000ms

// CS pin: PA4 confirmed from reference driver (HAL_SPI_MspInit / MX_SPI1_Init)
// Override in variant.h if your board differs.
#ifndef FLASH_CS_PIN
#define FLASH_CS_PIN PA4
#endif

// SPI1 pins confirmed from reference driver (HAL_SPI_MspInit, AF5):
//   PA5 = SPI1_SCK, PA6 = SPI1_MISO, PA7 = SPI1_MOSI
// In STM32duino, 'SPI1' is a HAL register macro - NOT an Arduino SPIClass object.
// We must construct SPIClass with explicit pin numbers; the framework maps them to SPI1 via AF.
// STM32WL LoRa uses SUBGHZSPI (internal), so SPI1 is entirely free for flash.
// Override any pin below in your variant.h if your board wiring differs.
#ifndef FLASH_SPI_MOSI
#define FLASH_SPI_MOSI PA7
#endif
#ifndef FLASH_SPI_MISO
#define FLASH_SPI_MISO PA6
#endif
#ifndef FLASH_SPI_SCK
#define FLASH_SPI_SCK  PA5
#endif

// SPI Flash Commands (W25Q series and compatible)
#define CMD_WRITE_ENABLE 0x06
#define CMD_WRITE_DISABLE 0x04
#define CMD_READ_STATUS_REG1 0x05
#define CMD_READ_STATUS_REG2 0x35
#define CMD_WRITE_STATUS_REG 0x01
#define CMD_PAGE_PROGRAM 0x02
#define CMD_QUAD_PAGE_PROGRAM 0x32
#define CMD_SECTOR_ERASE_4KB 0x20
#define CMD_BLOCK_ERASE_32KB 0x52
#define CMD_BLOCK_ERASE_64KB 0xD8
#define CMD_CHIP_ERASE 0xC7
#define CMD_READ_DATA 0x03
#define CMD_FAST_READ 0x0B
#define CMD_READ_JEDEC_ID 0x9F
#define CMD_POWER_DOWN 0xB9
#define CMD_RELEASE_POWER_DOWN 0xAB

// Status Register Bits
#define SR1_BUSY_MASK 0x01
#define SR1_WEL_MASK 0x02

// Use ##__VA_ARGS__ (GCC extension) to suppress trailing comma when called with no extra args
#if !CFG_DEBUG
#define _LFS_DBG(fmt, ...)
#else
#define _LFS_DBG(fmt, ...) printf("%s:%d (%s): " fmt "\n", __FILE__, __LINE__, __func__, ##__VA_ARGS__)
#endif

/**********************************************************************************************************************
 * SPI Hardware Access Layer
 **********************************************************************************************************************/

// Construct a dedicated SPIClass instance with the flash pins.
// STM32duino resolves MOSI/MISO/SCK to the correct SPI peripheral (SPI1) via pin AF lookup.
// Using a named object (not &SPI1) avoids the "lvalue required" error caused by the HAL macro.
static SPIClass _flash_spi_bus(FLASH_SPI_MOSI, FLASH_SPI_MISO, FLASH_SPI_SCK);
static SPIClass *_flash_spi = &_flash_spi_bus;
static SPISettings _flash_spi_settings(EXT_FLASH_SPI_FREQUENCY, MSBFIRST, SPI_MODE0);
static bool spi_flash_hw_initialized = false;

static bool _init_spi_hardware(void)
{
    if (spi_flash_hw_initialized)
        return true;

    // begin() configures the SPI peripheral and its GPIO alternate functions
    _flash_spi->begin();

    // Configure CS pin as GPIO output, idle high
    pinMode(FLASH_CS_PIN, OUTPUT);
    digitalWrite(FLASH_CS_PIN, HIGH);

    spi_flash_hw_initialized = true;
    return true;
}

// CS low: claim the SPI bus and assert chip select
static inline void _flash_cs_low(void)
{
    _flash_spi->beginTransaction(_flash_spi_settings);
    digitalWrite(FLASH_CS_PIN, LOW);
}

// CS high: deassert chip select and release the SPI bus
static inline void _flash_cs_high(void)
{
    digitalWrite(FLASH_CS_PIN, HIGH);
    _flash_spi->endTransaction();
}

// SPI transfer: send one byte and receive one byte simultaneously
static uint8_t _spi_transfer(uint8_t data)
{
    return _flash_spi->transfer(data);
}

// SPI write multiple bytes
static void _spi_write(const uint8_t *data, uint32_t len)
{
    for (uint32_t i = 0; i < len; i++) {
        _flash_spi->transfer(data[i]);
    }
}

// SPI read multiple bytes (send 0xFF dummy bytes to clock in data)
static void _spi_read(uint8_t *data, uint32_t len)
{
    for (uint32_t i = 0; i < len; i++) {
        data[i] = _flash_spi->transfer(0xFF);
    }
}

/**********************************************************************************************************************
 * SPI Flash Low-Level Operations
 **********************************************************************************************************************/

// Wait for flash to be ready (poll BUSY bit in Status Register 1)
static bool _flash_wait_ready(uint32_t timeout_ms)
{
    uint32_t start = millis();
    uint8_t status;

    do {
        _flash_cs_low();
        _spi_transfer(CMD_READ_STATUS_REG1);
        status = _spi_transfer(0xFF);
        _flash_cs_high();

        if ((status & SR1_BUSY_MASK) == 0)
            return true;

        delay(1);
    } while ((millis() - start) < timeout_ms);

    return false;
}

// Write enable (with WEL verification)
static bool _flash_write_enable(void)
{
    _flash_cs_low();
    _spi_transfer(CMD_WRITE_ENABLE);
    _flash_cs_high();

    // Verify WEL bit is set in Status Register 1
    _flash_cs_low();
    _spi_transfer(CMD_READ_STATUS_REG1);
    uint8_t status = _spi_transfer(0xFF);
    _flash_cs_high();

    if (!(status & SR1_WEL_MASK)) {
        _LFS_DBG("Write Enable failed, SR1=0x%02X", status);
        return false;
    }
    return true;
}

// Write disable
static void _flash_write_disable(void)
{
    _flash_cs_low();
    _spi_transfer(CMD_WRITE_DISABLE);
    _flash_cs_high();
}

// Send Deep Power-Down command (0xB9)
static void _flash_deep_power_down(void)
{
    if (!spi_flash_hw_initialized)
        return;

    _flash_cs_low();
    _spi_transfer(CMD_POWER_DOWN);
    _flash_cs_high();
}

// Send Release from Deep Power-Down command (0xAB)
static void _flash_release_power_down(void)
{
    if (!spi_flash_hw_initialized)
        return;

    _flash_cs_low();
    _spi_transfer(CMD_RELEASE_POWER_DOWN);
    _flash_cs_high();
}

// Read JEDEC ID (Manufacturer + Device ID)
static uint32_t _flash_read_jedec_id(void)
{
    uint32_t id = 0;

    _flash_cs_low();
    _spi_transfer(CMD_READ_JEDEC_ID);
    id  = (uint32_t)_spi_transfer(0xFF) << 16;
    id |= (uint32_t)_spi_transfer(0xFF) << 8;
    id |= (uint32_t)_spi_transfer(0xFF);
    _flash_cs_high();

    return id;
}

/**********************************************************************************************************************
 * LittleFS Disk I/O Functions
 **********************************************************************************************************************/

// Read from flash
static int _external_flash_read(const struct lfs_config *c, lfs_block_t block, lfs_off_t off, void *buffer, lfs_size_t size)
{
    LFS_UNUSED(c);

    if (!buffer || !size) {
        _LFS_DBG("Invalid parameter: buffer=%p, size=%u", buffer, size);
        return LFS_ERR_INVAL;
    }

    uint32_t address = (block * EXT_FLASH_BLOCK_SIZE) + off;

    if (!_flash_wait_ready(EXT_FLASH_T_PAGE_PROG_MS + 10)) {
        _LFS_DBG("Flash busy timeout before read at 0x%08X", address);
        return LFS_ERR_IO;
    }

    _flash_cs_low();
    _spi_transfer(CMD_READ_DATA);
    _spi_transfer((address >> 16) & 0xFF);
    _spi_transfer((address >> 8) & 0xFF);
    _spi_transfer(address & 0xFF);
    _spi_read((uint8_t *)buffer, size);
    _flash_cs_high();

    _LFS_DBG("Read %u bytes from 0x%08X (block %u, offset %u)", size, address, block, off);
    return LFS_ERR_OK;
}

// Program (write) to flash
static int _external_flash_prog(const struct lfs_config *c, lfs_block_t block, lfs_off_t off, const void *buffer,
                                lfs_size_t size)
{
    LFS_UNUSED(c);

    if (!buffer || !size) {
        return LFS_ERR_INVAL;
    }

    uint32_t address = (block * EXT_FLASH_BLOCK_SIZE) + off;
    const uint8_t *data = (const uint8_t *)buffer;
    uint32_t bytes_written = 0;

    _LFS_DBG("Programming %u bytes to 0x%08X (block %u, offset %u)", size, address, block, off);

    // Write in page-sized chunks (SPI flash requires page-aligned program operations)
    while (bytes_written < size) {
        uint32_t page_offset = (address + bytes_written) % EXT_FLASH_PAGE_SIZE;
        uint32_t chunk_size = EXT_FLASH_PAGE_SIZE - page_offset;
        if (chunk_size > (size - bytes_written)) {
            chunk_size = size - bytes_written;
        }

        if (!_flash_wait_ready(EXT_FLASH_T_SECTOR_ERASE_MS + 50)) {
            _LFS_DBG("Flash busy timeout before program");
            return LFS_ERR_IO;
        }

        if (!_flash_write_enable()) {
            _LFS_DBG("Write enable failed before page program");
            return LFS_ERR_IO;
        }

        _flash_cs_low();
        _spi_transfer(CMD_PAGE_PROGRAM);
        _spi_transfer(((address + bytes_written) >> 16) & 0xFF);
        _spi_transfer(((address + bytes_written) >> 8) & 0xFF);
        _spi_transfer((address + bytes_written) & 0xFF);
        _spi_write(data + bytes_written, chunk_size);
        _flash_cs_high();

        bytes_written += chunk_size;
    }

    if (!_flash_wait_ready(EXT_FLASH_T_SECTOR_ERASE_MS + 50)) {
        _LFS_DBG("Flash busy timeout after program");
        return LFS_ERR_IO;
    }

    // Read-back verification
    uint8_t verify_buf[32];
    uint32_t verified = 0;
    while (verified < size) {
        uint32_t chunk = (size - verified > sizeof(verify_buf)) ? sizeof(verify_buf) : (size - verified);
        uint32_t addr = (block * EXT_FLASH_BLOCK_SIZE) + off + verified;

        _flash_cs_low();
        _spi_transfer(CMD_READ_DATA);
        _spi_transfer((addr >> 16) & 0xFF);
        _spi_transfer((addr >> 8) & 0xFF);
        _spi_transfer(addr & 0xFF);
        _spi_read(verify_buf, chunk);
        _flash_cs_high();

        if (memcmp(verify_buf, (const uint8_t *)buffer + verified, chunk) != 0) {
            _LFS_DBG("Readback verify failed at 0x%08X", addr);
            return LFS_ERR_CORRUPT;
        }
        verified += chunk;
    }

    return LFS_ERR_OK;
}

// Erase a block (sector)
static int _external_flash_erase(const struct lfs_config *c, lfs_block_t block)
{
    LFS_UNUSED(c);

    uint32_t address = block * EXT_FLASH_BLOCK_SIZE;

    _LFS_DBG("Erasing block %u at 0x%08X", block, address);

    if (!_flash_wait_ready(EXT_FLASH_T_SECTOR_ERASE_MS + 50)) {
        _LFS_DBG("Flash busy timeout before erase");
        return LFS_ERR_IO;
    }

    if (!_flash_write_enable()) {
        _LFS_DBG("Write enable failed before erase");
        return LFS_ERR_IO;
    }

    _flash_cs_low();
    _spi_transfer(CMD_SECTOR_ERASE_4KB);
    _spi_transfer((address >> 16) & 0xFF);
    _spi_transfer((address >> 8) & 0xFF);
    _spi_transfer(address & 0xFF);
    _flash_cs_high();

    // ZB25VQ32 sector (4K) erase max time: 200ms
    if (!_flash_wait_ready(EXT_FLASH_T_SECTOR_ERASE_MS + 50)) {
        _LFS_DBG("Flash busy timeout after erase");
        return LFS_ERR_IO;
    }

    return LFS_ERR_OK;
}

// Sync operation (not needed for SPI flash, writes are immediate)
static int _external_flash_sync(const struct lfs_config *c)
{
    LFS_UNUSED(c);
    return LFS_ERR_OK;
}

/**********************************************************************************************************************
 * LittleFS Configuration
 **********************************************************************************************************************/

static struct lfs_config _ExternalFSConfig = {
    .context = NULL,

    .read = _external_flash_read,
    .prog = _external_flash_prog,
    .erase = _external_flash_erase,
    .sync = _external_flash_sync,

    // read_size = 1: SPI flash supports byte-granular reads, no minimum alignment needed.
    // prog_size = EXT_FLASH_PAGE_SIZE (256): matches the SPI flash page program granularity.
    // This keeps LittleFS read/prog buffers at 1+256 bytes instead of 4096+4096, saving ~8KB RAM.
    .read_size = 1,
    .prog_size = EXT_FLASH_PAGE_SIZE,
    .block_size = EXT_FLASH_BLOCK_SIZE,
    .block_count = EXT_FLASH_TOTAL_SIZE / EXT_FLASH_BLOCK_SIZE,
    .lookahead = 128,

    .read_buffer = NULL,
    .prog_buffer = NULL,
    .lookahead_buffer = NULL,
    .file_buffer = NULL,
};

// Global instance
ExternalFlashFS ExternalFS;

/**********************************************************************************************************************
 * ExternalFlashFS Class Implementation
 **********************************************************************************************************************/

ExternalFlashFS::ExternalFlashFS(void) : STM32_LittleFS(&_ExternalFSConfig), _flash_initialized(false) {}

bool ExternalFlashFS::initFlashHardware(void)
{
    if (_flash_initialized)
        return true;

    if (!_init_spi_hardware()) {
        _LFS_DBG("SPI hardware initialization failed");
        return false;
    }

    // Release from Deep Power-Down (needed after NVIC_SystemReset
    // which is not a full power-on reset)
    _flash_release_power_down();
    delay(1);

    // Re-assert CS idle high after release
    pinMode(FLASH_CS_PIN, OUTPUT);
    digitalWrite(FLASH_CS_PIN, HIGH);

    // Read and verify JEDEC ID
    uint32_t jedec_id = _flash_read_jedec_id();
    _LFS_DBG("SPI Flash JEDEC ID: 0x%06X", jedec_id);

    // Check if flash is responding (ID should not be 0x000000 or 0xFFFFFF)
    if (jedec_id == 0x000000 || jedec_id == 0xFFFFFF) {
        _LFS_DBG("Invalid JEDEC ID - flash not responding");
        return false;
    }

    // Verify this is a ZB25VQ32 (or compatible chip with same command set)
    if (jedec_id == ZB25VQ32_JEDEC_ID) {
        _LFS_DBG("Detected ZB25VQ32 (4MB SPI Flash)");
    } else {
        // Unknown chip: warn but continue - commands are compatible with W25Q/MX25L series
        _LFS_DBG("Unknown JEDEC ID 0x%06X - proceeding with standard command set", jedec_id);
    }

    _flash_initialized = true;
    return true;
}

bool ExternalFlashFS::begin(void)
{
    if (!_flash_initialized) {
        if (!initFlashHardware()) {
            return false;
        }
    }

    if (!STM32_LittleFS::begin()) {
        _LFS_DBG("Failed to mount, formatting...");

        this->format();

        if (!STM32_LittleFS::begin()) {
            _LFS_DBG("Failed to mount after format");
            return false;
        }
    }

    return true;
}

void ExternalFlashFS::powerDown(void)
{
    if (!_flash_initialized)
        return;

    end();

    _flash_deep_power_down();

    _flash_spi->end();

    pinMode(FLASH_CS_PIN, INPUT_ANALOG);
    pinMode(FLASH_SPI_SCK, INPUT_ANALOG);
    pinMode(FLASH_SPI_MISO, INPUT_ANALOG);
    pinMode(FLASH_SPI_MOSI, INPUT_ANALOG);

    spi_flash_hw_initialized = false;
    _flash_initialized = false;

    // LOG_INFO("SPI Flash Deep Power-Down");
}
