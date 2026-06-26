#pragma once

#include <stdint.h>

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)

#ifndef DRAGINO_STM32_SLEEP_WAKE_GATE
#define DRAGINO_STM32_SLEEP_WAKE_GATE 0
#endif

#ifndef DRAGINO_SLEEP_WAKE_HOLD_MS
#define DRAGINO_SLEEP_WAKE_HOLD_MS 5000UL
#endif

#ifndef DRAGINO_SLEEP_WAKE_BLINK_START_MS
#define DRAGINO_SLEEP_WAKE_BLINK_START_MS 3000UL
#endif

#ifndef DRAGINO_SLEEP_WAKE_SHORT_ACK_MS
#define DRAGINO_SLEEP_WAKE_SHORT_ACK_MS 3000UL
#endif

#ifndef DRAGINO_SLEEP_WAKE_SECOND_PRESS_MS
#define DRAGINO_SLEEP_WAKE_SECOND_PRESS_MS 1000UL
#endif

#ifndef DRAGINO_SLEEP_WAKE_DEBOUNCE_MS
#define DRAGINO_SLEEP_WAKE_DEBOUNCE_MS 40UL
#endif

#ifndef DRAGINO_SLEEP_WAKE_BLINK_INTERVAL_MS
#define DRAGINO_SLEEP_WAKE_BLINK_INTERVAL_MS 250UL
#endif

namespace dragino {

enum class SleepWakeGateResult {
    AcceptWake,
    RejectAndSleepAgain,
    TimerExpired,
};

class DraginoSleepWakeGate {
public:
    struct Context {
        bool foreverSleep = false;
        uint32_t deadlineRemainingMs = 0;
        bool buttonCurrentlyPressed = false;
    };

    struct Result {
        SleepWakeGateResult result = SleepWakeGateResult::RejectAndSleepAgain;
        uint32_t activeMs = 0;
        bool acceptedByLongPress = false;
        bool rejectedByRelease = false;
        bool timerExpired = false;
    };

    static Result run(const Context &ctx);
    static void prepareForSleep();

private:
    static void preparePins();
    static bool buttonPressed();
    static bool buttonPressedDebounced();
    static void ledGreen();
    static void ledOff();
    static void ledGreenBlink(uint32_t now);
};

} // namespace dragino

#endif // defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
