#pragma once

#include "concurrency/OSThread.h"

#include "configuration.h"

#include "sleep.h"

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)





namespace dragino {

#define DRAGINO_RGB_RED    PB13
#define DRAGINO_RGB_GREEN  PB14
#define DRAGINO_RGB_BLUE   PB12
#define DRAGINO_BUTTON_PIN PA8

#ifndef DRAGINO_ENABLE_EXTERNAL_ADC
#define DRAGINO_ENABLE_EXTERNAL_ADC 0
#endif

#if DRAGINO_ENABLE_EXTERNAL_ADC
#if !defined(DRAGINO_ADC_EXTERNAL_PIN) || !defined(DRAGINO_ADC_HELPER_PIN)
#error "Dragino ADC pins must be defined in variant.h when DRAGINO_ENABLE_EXTERNAL_ADC is enabled"
#endif
#endif

#ifndef DRAGINO_BUTTON_CLICK_WINDOW_MS
#define DRAGINO_BUTTON_CLICK_WINDOW_MS          700UL
#endif

#ifndef DRAGINO_BUTTON_DEBUG_SLEEP_ENABLE
#define DRAGINO_BUTTON_DEBUG_SLEEP_ENABLE       0
#endif

#ifndef DRAGINO_BUTTON_DEBUG_SLEEP_CLICK_COUNT
#define DRAGINO_BUTTON_DEBUG_SLEEP_CLICK_COUNT  5
#endif

#ifndef DRAGINO_BUTTON_FACTORY_CLICK_COUNT
#define DRAGINO_BUTTON_FACTORY_CLICK_COUNT      8
#endif

#ifndef DRAGINO_LONG_PRESS_SEND_MIN_MS
#define DRAGINO_LONG_PRESS_SEND_MIN_MS          3000UL
#endif

#ifndef DRAGINO_LONG_PRESS_SEND_MAX_MS
#define DRAGINO_LONG_PRESS_SEND_MAX_MS          8000UL
#endif

#ifndef DRAGINO_LONG_PRESS_BOOTLOADER_MS
#define DRAGINO_LONG_PRESS_BOOTLOADER_MS        10000UL
#endif

#define DRAGINO_LED_ON_MS                       3000
#define DRAGINO_BLINK_MS                        3000
#define DRAGINO_BLINK_INTERVAL_MS               250
#define DRAGINO_BUTTON_INIT_DELAY_MS            5000

class DraginoHardware : private concurrency::OSThread
{
public:
    DraginoHardware();

    void setRed();
    void setGreen();
    void setBlue();
    void startGreenBlink();
    void startBlueBlink();
    void startRedBlink();
    void off();

    uint16_t getExternalVoltageMv() const { return externalVoltageMv_; }

    void sensorPowerOn();
    void sensorPowerOff();

    bool isNetworkJoined();

    void Turn_off();
    bool resumeAfterStop();

protected:
    int32_t runOnce() override;

private:
    enum State { IDLE, PRESSED };
    enum HoldZone { HOLD_NONE, HOLD_SEND_CANDIDATE, HOLD_DEAD_ZONE, HOLD_BOOTLOADER_CANDIDATE };
    enum BlinkType { NONE, GREEN_BLINK, RED_BLINK, BLUE_BLINK };

    void initGPIO();
    void testLED();
    void ledOff();
    void handleButton();
    void handlePendingClicks(uint32_t now);
    void handleDeferredActions(uint32_t now);
    void handleLED();
    void showShortClickFeedback(uint32_t now);
    void recordShortClick(uint32_t now);
    void handleSingleClick();
    void requestManualBusinessUpload();
    void enterBootloaderFromButton();
    void enterDebugSleep();
    void showBlueBlinkFrame(uint32_t now);
    void showBlueGreenBlinkFrame(uint32_t now);
    void factoryReset();

#if DRAGINO_ENABLE_EXTERNAL_ADC
    void readADC();
#endif

    

    int notifyDeepSleepCb(void *unused = nullptr);
    CallbackObserver<DraginoHardware, void *> deepSleepObserver =
        CallbackObserver<DraginoHardware, void *>(this, &DraginoHardware::notifyDeepSleepCb);


    State state_ = IDLE;
    HoldZone holdZone_ = HOLD_NONE;
    BlinkType blinkType_ = NONE;
    uint32_t pressTime_ = 0;
    uint32_t ledOffTime_ = 0;
    uint32_t blinkEndTime_ = 0;
    uint32_t buttonReadyTime_ = 0;
    uint8_t clickCount_ = 0;
    uint32_t clickWindowUntil_ = 0;
    bool pendingFactoryReset_ = false;
    uint32_t factoryResetAtMs_ = 0;

#if DRAGINO_ENABLE_EXTERNAL_ADC
    uint32_t lastAdcTime_ = 0;
#endif

    uint16_t externalVoltageMv_ = 0;
    bool sensorPowerEnabled_ = false;

};

extern DraginoHardware* draginoHardware;

}

#endif // defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
