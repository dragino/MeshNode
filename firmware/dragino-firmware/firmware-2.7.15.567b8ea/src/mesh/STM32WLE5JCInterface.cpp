#include "configuration.h"

#ifdef ARCH_STM32WL
#include <SubGhz.h>

#include "STM32WLE5JCInterface.h"
#include "error.h"

#ifndef STM32WLx_MAX_POWER
#define STM32WLx_MAX_POWER 22
#endif

static void subghzWriteCommand(uint8_t cmd, const uint8_t *data, size_t len)
{
    SubGhz.SPI.beginTransaction(SubGhz.spi_settings);
    SubGhz.setNssActive(true);
    while (SubGhz.isBusy()) {
    }

    SubGhz.SPI.transfer(cmd);
    for (size_t i = 0; i < len; ++i) {
        SubGhz.SPI.transfer(data[i]);
    }

    SubGhz.setNssActive(false);
    SubGhz.SPI.endTransaction();
}

static void subghzWriteRegister(uint16_t reg, uint8_t value)
{
    SubGhz.SPI.beginTransaction(SubGhz.spi_settings);
    SubGhz.setNssActive(true);
    while (SubGhz.isBusy()) {
    }

    SubGhz.SPI.transfer(0x0D); // SUBGHZ write register command
    SubGhz.SPI.transfer((reg >> 8) & 0xFF);
    SubGhz.SPI.transfer(reg & 0xFF);
    SubGhz.SPI.transfer(value);

    SubGhz.setNssActive(false);
    SubGhz.SPI.endTransaction();
}

STM32WLE5JCInterface::STM32WLE5JCInterface(LockingArduinoHal *hal, RADIOLIB_PIN_TYPE cs, RADIOLIB_PIN_TYPE irq,
                                           RADIOLIB_PIN_TYPE rst, RADIOLIB_PIN_TYPE busy)
    : SX126xInterface(hal, cs, irq, rst, busy)
{
}

bool STM32WLE5JCInterface::init()
{
    RadioLibInterface::init();

// https://github.com/Seeed-Studio/LoRaWan-E5-Node/blob/main/Middlewares/Third_Party/SubGHz_Phy/stm32_radio_driver/radio_driver.c
#if (!defined(_VARIANT_RAK3172_))
    setTCXOVoltage(1.7);
#endif

    lora.setRfSwitchTable(rfswitch_pins, rfswitch_table);

    limitPower(STM32WLx_MAX_POWER);

    int res = lora.begin(getFreq(), bw, sf, cr, syncWord, power, preambleLength, tcxoVoltage);

    LOG_INFO("STM32WLx init result %d", res);

    LOG_INFO("Frequency set to %f", getFreq());
    LOG_INFO("Bandwidth set to %f", bw);
    LOG_INFO("Power output set to %d", power);

    if (res == RADIOLIB_ERR_NONE)
        startReceive(); // start receiving

    return res == RADIOLIB_ERR_NONE;
}

bool STM32WLE5JCInterface::sleep()
{
    LOG_DEBUG("STM32WLx entering sleep mode");

    setStandby();

    for (size_t i = 0; i < Module::RFSWITCH_MAX_PINS; ++i) {
        if (rfswitch_pins[i] != RADIOLIB_NC) {
            pinMode(rfswitch_pins[i], OUTPUT);
            digitalWrite(rfswitch_pins[i], LOW);
        }
    }

    const uint8_t standbyRc[] = {RADIOLIB_SX126X_STANDBY_RC};
    subghzWriteCommand(RADIOLIB_SX126X_CMD_SET_STANDBY, standbyRc, sizeof(standbyRc));
    delay(1);

    subghzWriteRegister(0x08DC, 0x20); // SMPS default: SMPS_DRV_40

    SubGhz.clearPendingInterrupt();
    SubGhz.disableInterrupt();

    const uint8_t sleepCfg[] = {RADIOLIB_SX126X_SLEEP_START_WARM | RADIOLIB_SX126X_SLEEP_RTC_OFF};
    subghzWriteCommand(RADIOLIB_SX126X_CMD_SET_SLEEP, sleepCfg, sizeof(sleepCfg));
    delay(2);

    return true;
}

#endif // ARCH_STM32WL
