#include "configuration.h"

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)

#include "DraginoHardware.h"
#include "DebugConfiguration.h"
#include "FSCommon.h"
#include "freertosinc.h"
#include "mesh/NodeDB.h"
#include "PrivateConfig.h"
#include "power.h"
#include "ExternalFlashFS.h"

#include <Wire.h>
#include <stm32wlxx_hal_subghz.h>
// extern SUBGHZ_HandleTypeDef hsubghz;  // Defined by the Arduino STM32 framework.

#include "DraginoBluetooth.h"
#include "DraginoBootControlPage.h"
#include "DraginoModule.h"

namespace dragino {

#ifndef DRAGINO_SLEEP_DEBUG_TRACE
#define DRAGINO_SLEEP_DEBUG_TRACE 0
#endif

static void sleepDebugTrace(const char *message)
{
#if DRAGINO_SLEEP_DEBUG_TRACE
    Serial.begin(SERIAL_BAUD);
    Serial.print("[SLPDBG] ");
    Serial.println(message);
    Serial.flush();
#else
    (void)message;
#endif
}

static void sleepDebugTraceResetFlags()
{
#if DRAGINO_SLEEP_DEBUG_TRACE && defined(ARCH_STM32WL) && defined(__HAL_RCC_GET_FLAG)
    Serial.begin(SERIAL_BAUD);
    Serial.print("[SLPDBG] reset flags:");
    bool any = false;

#ifdef RCC_FLAG_PINRST
    if (__HAL_RCC_GET_FLAG(RCC_FLAG_PINRST) != 0U) {
        Serial.print(" PIN");
        any = true;
    }
#endif
#ifdef RCC_FLAG_BORRST
    if (__HAL_RCC_GET_FLAG(RCC_FLAG_BORRST) != 0U) {
        Serial.print(" BOR");
        any = true;
    }
#endif
#ifdef RCC_FLAG_SFTRST
    if (__HAL_RCC_GET_FLAG(RCC_FLAG_SFTRST) != 0U) {
        Serial.print(" SFT");
        any = true;
    }
#endif
#ifdef RCC_FLAG_IWDGRST
    if (__HAL_RCC_GET_FLAG(RCC_FLAG_IWDGRST) != 0U) {
        Serial.print(" IWDG");
        any = true;
    }
#endif
#ifdef RCC_FLAG_WWDGRST
    if (__HAL_RCC_GET_FLAG(RCC_FLAG_WWDGRST) != 0U) {
        Serial.print(" WWDG");
        any = true;
    }
#endif
#ifdef RCC_FLAG_LPWRRST
    if (__HAL_RCC_GET_FLAG(RCC_FLAG_LPWRRST) != 0U) {
        Serial.print(" LPWR");
        any = true;
    }
#endif
#ifdef RCC_FLAG_OBLRST
    if (__HAL_RCC_GET_FLAG(RCC_FLAG_OBLRST) != 0U) {
        Serial.print(" OBL");
        any = true;
    }
#endif

    if (!any) {
        Serial.print(" none");
    }
    Serial.println();
    Serial.flush();

#ifdef __HAL_RCC_CLEAR_RESET_FLAGS
    __HAL_RCC_CLEAR_RESET_FLAGS();
#endif
#endif
}

#if defined(ARCH_STM32WL)
static void rebootToBootloader()
{
    delay(50);
    __disable_irq();
    SysTick->CTRL = 0;
    SysTick->LOAD = 0;
    SysTick->VAL = 0;
    SCB->ICSR = SCB_ICSR_PENDSTCLR_Msk | SCB_ICSR_PENDSVCLR_Msk;
    __DSB();
    __ISB();
    NVIC_SystemReset();
}
#endif

DraginoHardware* draginoHardware = nullptr;

DraginoHardware::DraginoHardware() : OSThread("DraginoHardware", 50)
{
    draginoHardware = this;
    sleepDebugTraceResetFlags();
    initGPIO();
    deepSleepObserver.observe(&notifyDeepSleep);
}

void DraginoHardware::initGPIO()
{
    pinMode(DRAGINO_RGB_RED, OUTPUT);
    pinMode(DRAGINO_RGB_GREEN, OUTPUT);
    pinMode(DRAGINO_RGB_BLUE, OUTPUT);
    pinMode(DRAGINO_BUTTON_PIN, INPUT_PULLUP);

#ifdef EXTERNAL_SENSOR_CONTROL_PIN
    pinMode(EXTERNAL_SENSOR_CONTROL_PIN, OUTPUT);
    digitalWrite(EXTERNAL_SENSOR_CONTROL_PIN, HIGH);
    sensorPowerEnabled_ = true;
#endif

#if DRAGINO_ENABLE_EXTERNAL_ADC
    pinMode(DRAGINO_ADC_EXTERNAL_PIN, INPUT_ANALOG);
    pinMode(DRAGINO_ADC_HELPER_PIN, INPUT_ANALOG);
    analogReadResolution(12);
#endif
    
    off();
    buttonReadyTime_ = millis() + DRAGINO_BUTTON_INIT_DELAY_MS;
}

void DraginoHardware::setRed()
{
    digitalWrite(DRAGINO_RGB_RED, HIGH);
    digitalWrite(DRAGINO_RGB_GREEN, LOW);
    digitalWrite(DRAGINO_RGB_BLUE, LOW);
}

void DraginoHardware::setGreen()
{
    digitalWrite(DRAGINO_RGB_RED, LOW);
    digitalWrite(DRAGINO_RGB_GREEN, HIGH);
    digitalWrite(DRAGINO_RGB_BLUE, LOW);
}

void DraginoHardware::setBlue()
{
    digitalWrite(DRAGINO_RGB_RED, LOW);
    digitalWrite(DRAGINO_RGB_GREEN, LOW);
    digitalWrite(DRAGINO_RGB_BLUE, HIGH);
}

void DraginoHardware::startGreenBlink()
{
    blinkType_ = GREEN_BLINK;
    blinkEndTime_ = millis() + DRAGINO_BLINK_MS;
}

void DraginoHardware::startBlueBlink()
{
    blinkType_ = BLUE_BLINK;
    blinkEndTime_ = millis() + DRAGINO_BLINK_MS;
}

void DraginoHardware::startRedBlink()
{
    blinkType_ = RED_BLINK;
    blinkEndTime_ = millis() + DRAGINO_BLINK_MS;
}

void DraginoHardware::off()
{
    digitalWrite(DRAGINO_RGB_RED, LOW);
    digitalWrite(DRAGINO_RGB_GREEN, LOW);
    digitalWrite(DRAGINO_RGB_BLUE, LOW);
    ledOffTime_ = 0;
    blinkEndTime_ = 0;
    blinkType_ = NONE;
}

void DraginoHardware::ledOff()
{
    digitalWrite(DRAGINO_RGB_RED, LOW);
    digitalWrite(DRAGINO_RGB_GREEN, LOW);
    digitalWrite(DRAGINO_RGB_BLUE, LOW);
}

void DraginoHardware::testLED()
{
    digitalWrite(DRAGINO_RGB_RED, HIGH);
    digitalWrite(DRAGINO_RGB_GREEN, LOW);
    digitalWrite(DRAGINO_RGB_BLUE, LOW);
    delay(1000);
    
    digitalWrite(DRAGINO_RGB_RED, LOW);
    digitalWrite(DRAGINO_RGB_GREEN, HIGH);
    delay(1000);
    
    digitalWrite(DRAGINO_RGB_GREEN, LOW);
    digitalWrite(DRAGINO_RGB_BLUE, HIGH);
    delay(1000);
    
    off();
}

#if DRAGINO_ENABLE_EXTERNAL_ADC
void DraginoHardware::readADC()
{
    uint32_t now = millis();
    if (now - lastAdcTime_ < DRAGINO_ADC_INTERVAL_MS) {
        return;
    }
    lastAdcTime_ = now;

    uint32_t sum = 0;
    for (int i = 0; i < DRAGINO_ADC_SAMPLES; i++) {
        sum += analogRead(DRAGINO_ADC_EXTERNAL_PIN);
    }

    uint32_t raw = sum / DRAGINO_ADC_SAMPLES;
    float adcMv = (raw * DRAGINO_ADC_VREF_MV) / (float)DRAGINO_ADC_MAX_VALUE;
    externalVoltageMv_ = (uint16_t)(adcMv * DRAGINO_ADC_EXTERNAL_MULTIPLIER);

    LOG_INFO("ADC external: raw=%lu adc=%lumV vin=%umV",
             raw,
             (uint32_t)adcMv,
             externalVoltageMv_);
}
#endif

void DraginoHardware::sensorPowerOn()
{
#ifdef EXTERNAL_SENSOR_CONTROL_PIN
    pinMode(EXTERNAL_SENSOR_CONTROL_PIN, OUTPUT);
    digitalWrite(EXTERNAL_SENSOR_CONTROL_PIN, HIGH);
    if (sensorPowerEnabled_) {
        return;
    }
    sensorPowerEnabled_ = true;
    LOG_INFO("Sensor power enabled");
#endif
}
void DraginoHardware::sensorPowerOff()
{
#ifdef EXTERNAL_SENSOR_CONTROL_PIN
    // PA0 is POWER_5V on this board; do not pull it low during sleep shutdown.
#endif
}


void DraginoHardware::Turn_off()
{
#if !DRAGINO_SHT3X_ENABLE
    sensorPowerOff();
#endif

    // RGB off
    pinMode(DRAGINO_RGB_RED, INPUT_ANALOG);
    // digitalWrite(DRAGINO_RGB_RED, LOW);
    pinMode(DRAGINO_RGB_GREEN, INPUT_ANALOG);
    // digitalWrite(DRAGINO_RGB_GREEN, LOW);
    pinMode(DRAGINO_RGB_BLUE, INPUT_ANALOG);
    // digitalWrite(DRAGINO_RGB_BLUE, LOW);



    // Serial2 off
    pinMode(PIN_SERIAL2_TX, INPUT_ANALOG);
    pinMode(PIN_SERIAL2_RX, INPUT_ANALOG);
    
    // IIC off
    pinMode(PA11, INPUT_ANALOG);
    pinMode(PA12, INPUT_ANALOG);

    // RF Switch off
    // pinMode(PC0, INPUT_ANALOG);
    pinMode(PC0, OUTPUT);
    digitalWrite(PC0, LOW);
    pinMode(PC6, OUTPUT);
    digitalWrite(PC6, LOW);
    // pinMode(PC6, INPUT_ANALOG);

    // SPI Flash off
    ExternalFS.powerDown();

    pinMode(PA4, INPUT_ANALOG);
    pinMode(PA5, INPUT_ANALOG);
    pinMode(PA6, INPUT_ANALOG);
    pinMode(PA7, INPUT_ANALOG);


    // Bluetooth off
    pinMode(DRAGINO_BT_LINK_PIN, INPUT_ANALOG);
//    digitalWrite(DRAGINO_BT_LINK_PIN, LOW);
    pinMode(DRAGINO_BT_WORK_PIN, INPUT_ANALOG);
//    digitalWrite(DRAGINO_BT_WORK_PIN, LOW);

    pinMode(DRAGINO_BT_KEY_PIN, INPUT_ANALOG);
    pinMode(DRAGINO_BT_RST_PIN, INPUT_ANALOG);
//    digitalWrite(DRAGINO_BT_KEY_PIN, LOW);
//  digitalWrite(DRAGINO_BT_RST_PIN, LOW);


    // Serial off
    Serial.end();
//  Serial1.end();
    pinMode(PIN_SERIAL_RX, INPUT_ANALOG);
    pinMode(PIN_SERIAL_TX, INPUT_ANALOG);
    // digitalWrite(PIN_SERIAL_RX,LOW);
    // digitalWrite(PIN_SERIAL_TX,LOW);


    // other pins off
    pinMode(PA1, INPUT_ANALOG);
    pinMode(PA9, INPUT_ANALOG);
    pinMode(PA10, INPUT_ANALOG);
//    pinMode(PA13, INPUT_ANALOG);

    pinMode(PB0, INPUT_ANALOG);
    pinMode(PB1, INPUT_ANALOG);
    pinMode(PB2, INPUT_ANALOG);
    pinMode(PB3, INPUT_ANALOG);
    pinMode(PB4, INPUT_ANALOG);
    pinMode(PB5, INPUT_ANALOG);
    pinMode(PB9, INPUT_ANALOG);
    pinMode(PB10, INPUT_ANALOG);
    pinMode(PB11, INPUT_ANALOG);
    pinMode(PB15, INPUT_ANALOG);

    pinMode(PC2, INPUT_ANALOG);
    pinMode(PC3, INPUT_ANALOG);
    pinMode(PC13, INPUT_ANALOG);

/* 
    // ====== Full RF subsystem shutdown ======

    // 1) Keep the radio in STANDBY_RC mode so it does not depend on TCXO/HSE32.
    uint8_t standbyMode = 0x00; // STDBY_RC
    HAL_SUBGHZ_ExecSetCmd(&hsubghz, RADIO_SET_STANDBY, &standbyMode, 1);
    HAL_Delay(1);

    // 2) Reset the SMPS drive configuration to its default value.
    //    SMPS drive register: 0x08DC, default = 0x20
    uint8_t smpsDefault = 0x20;
    HAL_SUBGHZ_WriteRegisters(&hsubghz, 0x08DC, &smpsDefault, 1);

    // 3) Send the SetSleep command with warm start enabled.
    uint8_t sleepConfig = 0x04; // bit2=WarmStart=1, bit1=Reset=0, bit0=WakeUpRTC=0
    HAL_SUBGHZ_ExecSetCmd(&hsubghz, RADIO_SET_SLEEP, &sleepConfig, 1);
    HAL_Delay(2);

    // 4) Disable the SUBGHZSPI clock, matching the reference MspDeInit flow.
    __HAL_RCC_SUBGHZSPI_CLK_DISABLE();
    HAL_NVIC_DisableIRQ(SUBGHZ_Radio_IRQn);

    // 5) Put RF switch pins into analog mode; PC0/PC6 are already handled in Turn_off().

    // 6) Disable DBGMCU.
    ;
    HAL_SUBGHZ_ExecSetCmd(&hsubghz, RADIO_SET_STANDBY, &standbyMode, 1);
    HAL_Delay(1);

    HAL_DBGMCU_DisableDBGSleepMode();
    HAL_DBGMCU_DisableDBGStopMode();
    HAL_DBGMCU_DisableDBGStandbyMode();
*/

    delay(100);



}

bool DraginoHardware::resumeAfterStop()
{
    bool fsOk = true;

    Serial.begin(SERIAL_BAUD);
    if (console) {
        console->setDestination(&Serial);
        console->resume();
        console->delayNextRun(0);
    }

#if HAS_GPS && defined(GPS_SERIAL_PORT)
    GPS_SERIAL_PORT.begin(GPS_BAUDRATE);
#endif

#if !MESHTASTIC_EXCLUDE_I2C
#if defined(I2C_SDA) && defined(ARCH_STM32WL)
    Wire.begin((uint32_t)I2C_SDA, (uint32_t)I2C_SCL);
#elif HAS_WIRE
    Wire.begin();
#endif
#endif

    initGPIO();

    state_ = IDLE;
    holdZone_ = HOLD_NONE;
    pressTime_ = 0;
    clickCount_ = 0;
    clickWindowUntil_ = 0;
    pendingFactoryReset_ = false;
    factoryResetAtMs_ = 0;

#if defined(ARCH_STM32WL)
    fsOk = FSBegin();
    if (!fsOk) {
        LOG_WARN("Dragino resume: filesystem mount failed");
    }
#endif

    setIntervalFromNow(0);
    return fsOk;
}

int DraginoHardware::notifyDeepSleepCb(void *unused)
{
    sleepDebugTrace("hardware notify begin");
    

    // LEDRGB off
    off();
    sleepDebugTrace("hardware led off");

    delay(100); // Ensure the pin state is settled before sleeping
    sleepDebugTrace("hardware notify end");
    return 0;
}


bool DraginoHardware::isNetworkJoined()
{
    return privateConfig.isEnrolled();
}

int32_t DraginoHardware::runOnce()
{
    uint32_t now = millis();

    handleButton();
    handlePendingClicks(now);
    handleDeferredActions(now);
    handleLED();
#if DRAGINO_ENABLE_EXTERNAL_ADC
    readADC();
#endif
    return 50;
}

void DraginoHardware::handleButton()
{
    uint32_t now = millis();
    
    if (now < buttonReadyTime_) {
        return;
    }
    
    bool pressed = (digitalRead(DRAGINO_BUTTON_PIN) == LOW);

    switch (state_) {
    case IDLE:
        if (pressed) {
            showShortClickFeedback(now);
            state_ = PRESSED;
            pressTime_ = now;
            holdZone_ = HOLD_NONE;
        }
        break;

    case PRESSED:
        if (!pressed) {
            uint32_t holdTime = now - pressTime_;

            if (holdTime < DRAGINO_LONG_PRESS_SEND_MIN_MS) {
                recordShortClick(now);
            } else if (holdTime < DRAGINO_LONG_PRESS_SEND_MAX_MS) {
                off();
                requestManualBusinessUpload();
            } else if (holdTime < DRAGINO_LONG_PRESS_BOOTLOADER_MS) {
                off();
                LOG_INFO("Button: release in dead zone, cancel");
            } else {
                off();
                enterBootloaderFromButton();
            }

            state_ = IDLE;
            holdZone_ = HOLD_NONE;
        } else {
            uint32_t holdTime = now - pressTime_;

            if (holdTime >= DRAGINO_LONG_PRESS_BOOTLOADER_MS) {
                if (holdZone_ != HOLD_BOOTLOADER_CANDIDATE) {
                    holdZone_ = HOLD_BOOTLOADER_CANDIDATE;
                    clickCount_ = 0;
                    clickWindowUntil_ = 0;
                    LOG_INFO("Button: bootloader candidate");
                }
                showBlueGreenBlinkFrame(now);
            } else if (holdTime >= DRAGINO_LONG_PRESS_SEND_MAX_MS) {
                if (holdZone_ != HOLD_DEAD_ZONE) {
                    holdZone_ = HOLD_DEAD_ZONE;
                    clickCount_ = 0;
                    clickWindowUntil_ = 0;
                    off();
                    LOG_INFO("Button: dead zone");
                }
            } else if (holdTime >= DRAGINO_LONG_PRESS_SEND_MIN_MS) {
                if (holdZone_ != HOLD_SEND_CANDIDATE) {
                    holdZone_ = HOLD_SEND_CANDIDATE;
                    clickCount_ = 0;
                    clickWindowUntil_ = 0;
                    LOG_INFO("Button: manual upload candidate");
                }
                showBlueBlinkFrame(now);
            }
        }
        break;
    }
}

void DraginoHardware::recordShortClick(uint32_t now)
{
    if (clickCount_ < 255) {
        clickCount_++;
    }
    showShortClickFeedback(now);
    clickWindowUntil_ = now + DRAGINO_BUTTON_CLICK_WINDOW_MS;
}

void DraginoHardware::showShortClickFeedback(uint32_t now)
{
    if (isNetworkJoined()) {
        setGreen();
    } else {
        setBlue();
    }
    ledOffTime_ = now + DRAGINO_LED_ON_MS;
}

void DraginoHardware::handlePendingClicks(uint32_t now)
{
    if (clickCount_ == 0 || state_ != IDLE) {
        return;
    }

    if ((int32_t)(now - clickWindowUntil_) < 0) {
        return;
    }

    uint8_t count = clickCount_;
    clickCount_ = 0;
    clickWindowUntil_ = 0;

    if (count == DRAGINO_BUTTON_FACTORY_CLICK_COUNT) {
        startRedBlink();
        pendingFactoryReset_ = true;
        factoryResetAtMs_ = now + DRAGINO_BLINK_MS;
        LOG_INFO("Button: factory reset armed by %u clicks", count);
        return;
    }

#if DRAGINO_BUTTON_DEBUG_SLEEP_ENABLE
    if (count == DRAGINO_BUTTON_DEBUG_SLEEP_CLICK_COUNT) {
        sleepDebugTrace("debug sleep click matched");
        LOG_INFO("Button: debug sleep by %u clicks", count);
        enterDebugSleep();
        return;
    }
#endif

    if (count == 1) {
        handleSingleClick();
        return;
    }

    LOG_INFO("Button: ignored click count=%u", count);
}

void DraginoHardware::handleDeferredActions(uint32_t now)
{
    if (pendingFactoryReset_ && (int32_t)(now - factoryResetAtMs_) >= 0) {
        pendingFactoryReset_ = false;
        factoryReset();
    }
}

void DraginoHardware::handleSingleClick()
{
    if (draginoBluetooth) {
        draginoBluetooth->toggle();
    }
    showShortClickFeedback(millis());
    if (isNetworkJoined()) {
        LOG_INFO("Short press: BT toggle, network joined");
    } else {
        LOG_INFO("Short press: BT toggle, not joined");
    }
}

void DraginoHardware::requestManualBusinessUpload()
{
    if (draginoModule) {
        LOG_INFO("Button: manual upload");
        draginoModule->requestFactoryManualUpload();
    } else {
        LOG_WARN("Button: DraginoModule unavailable, manual upload skipped");
    }
}

void DraginoHardware::enterBootloaderFromButton()
{
    LOG_INFO("Button: enter bootloader");
    if (!requestBootloaderUpgrade(BootUpgradeReason::SerialUart)) {
        LOG_WARN("Button: failed to set bootloader request");
        startRedBlink();
        return;
    }
#if defined(ARCH_STM32WL)
    rebootToBootloader();
#else
    NVIC_SystemReset();
#endif
}

void DraginoHardware::enterDebugSleep()
{
#if DRAGINO_BUTTON_DEBUG_SLEEP_ENABLE
    sleepDebugTrace("debug sleep enter");
    startGreenBlink();
    setGreen();
    sleepDebugTrace("debug sleep led set");
    LOG_INFO("Button: entering debug sleep");
    delay(200);
    sleepDebugTrace("debug sleep before doDeepSleep skipSave=1");
    doDeepSleep(portMAX_DELAY, true, true);
    sleepDebugTrace("debug sleep returned from doDeepSleep");
#endif
}

void DraginoHardware::showBlueBlinkFrame(uint32_t now)
{
    ledOffTime_ = 0;
    bool on = ((now / DRAGINO_BLINK_INTERVAL_MS) % 2 == 0);
    if (on) {
        setBlue();
    } else {
        ledOff();
    }
}

void DraginoHardware::showBlueGreenBlinkFrame(uint32_t now)
{
    ledOffTime_ = 0;
    bool blue = ((now / DRAGINO_BLINK_INTERVAL_MS) % 2 == 0);
    if (blue) {
        setBlue();
    } else {
        setGreen();
    }
}

void DraginoHardware::handleLED()
{
    uint32_t now = millis();

    if (blinkEndTime_ > 0) {
        if (now >= blinkEndTime_) {
            off();
            return;
        }
        bool on = ((now / DRAGINO_BLINK_INTERVAL_MS) % 2 == 0);
        if (blinkType_ == GREEN_BLINK) {
            if (on) setGreen();
            else ledOff();
        } else if (blinkType_ == BLUE_BLINK) {
            if (on) setBlue();
            else ledOff();
        } else if (blinkType_ == RED_BLINK) {
            if (on) setRed();
            else ledOff();
        }
        return;
    }

    if (ledOffTime_ > 0 && now >= ledOffTime_) {
        off();
    }
}

void DraginoHardware::factoryReset()
{
    LOG_INFO("Factory reset triggered");
    nodeDB->factoryReset();
    NVIC_SystemReset();
}

}

#endif // defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
