#include "DraginoSleepWakeGate.h"

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)

#include "DraginoHardware.h"
#include <Arduino.h>

namespace dragino {

void DraginoSleepWakeGate::preparePins()
{
    pinMode(DRAGINO_RGB_RED, OUTPUT);
    pinMode(DRAGINO_RGB_GREEN, OUTPUT);
    pinMode(DRAGINO_RGB_BLUE, OUTPUT);
    pinMode(DRAGINO_BUTTON_PIN, INPUT_PULLUP);
    ledOff();
}

void DraginoSleepWakeGate::prepareForSleep()
{
    ledOff();
    pinMode(DRAGINO_RGB_RED, INPUT_ANALOG);
    pinMode(DRAGINO_RGB_GREEN, INPUT_ANALOG);
    pinMode(DRAGINO_RGB_BLUE, INPUT_ANALOG);
    pinMode(DRAGINO_BUTTON_PIN, INPUT_PULLUP);
}

bool DraginoSleepWakeGate::buttonPressed()
{
    pinMode(DRAGINO_BUTTON_PIN, INPUT_PULLUP);
    return digitalRead(DRAGINO_BUTTON_PIN) == LOW;
}

bool DraginoSleepWakeGate::buttonPressedDebounced()
{
    bool first = buttonPressed();
    delay(DRAGINO_SLEEP_WAKE_DEBOUNCE_MS);
    return first && buttonPressed();
}

void DraginoSleepWakeGate::ledGreen()
{
    digitalWrite(DRAGINO_RGB_RED, LOW);
    digitalWrite(DRAGINO_RGB_GREEN, HIGH);
    digitalWrite(DRAGINO_RGB_BLUE, LOW);
}

void DraginoSleepWakeGate::ledOff()
{
    digitalWrite(DRAGINO_RGB_RED, LOW);
    digitalWrite(DRAGINO_RGB_GREEN, LOW);
    digitalWrite(DRAGINO_RGB_BLUE, LOW);
}

void DraginoSleepWakeGate::ledGreenBlink(uint32_t now)
{
    bool on = ((now / DRAGINO_SLEEP_WAKE_BLINK_INTERVAL_MS) % 2) == 0;
    if (on) {
        ledGreen();
    } else {
        ledOff();
    }
}

DraginoSleepWakeGate::Result DraginoSleepWakeGate::run(const Context &ctx)
{
    Result result;
    preparePins();
    ledGreen();

    uint32_t start = millis();
    uint32_t holdStart = 0;
    bool holding = false;

    if (ctx.buttonCurrentlyPressed && buttonPressedDebounced()) {
        holding = true;
        holdStart = millis();
    }

    while (true) {
        uint32_t now = millis();
        uint32_t activeMs = now - start;

        if (!ctx.foreverSleep && activeMs >= ctx.deadlineRemainingMs) {
            ledOff();
            result.result = SleepWakeGateResult::TimerExpired;
            result.activeMs = activeMs;
            result.timerExpired = true;
            return result;
        }

        bool pressed = buttonPressedDebounced();

        if (pressed) {
            if (!holding) {
                holding = true;
                holdStart = now;
            }

            uint32_t holdMs = now - holdStart;
            if (holdMs >= DRAGINO_SLEEP_WAKE_BLINK_START_MS) {
                ledGreenBlink(now);
            } else {
                ledGreen();
            }
        } else if (holding) {
            uint32_t holdMs = now - holdStart;
            ledOff();
            result.activeMs = activeMs;

            if (holdMs >= DRAGINO_SLEEP_WAKE_BLINK_START_MS) {
                result.result = SleepWakeGateResult::AcceptWake;
                result.acceptedByLongPress = true;
            } else {
                result.result = SleepWakeGateResult::RejectAndSleepAgain;
                result.rejectedByRelease = true;
            }
            return result;
        } else {
            ledGreen();
            if (activeMs >= DRAGINO_SLEEP_WAKE_BLINK_START_MS) {
                ledOff();
                result.result = SleepWakeGateResult::RejectAndSleepAgain;
                result.activeMs = activeMs;
                return result;
            }
        }

        delay(10);
    }
}

} // namespace dragino

#endif // defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
