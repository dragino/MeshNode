#include "RTC.h"
#include "configuration.h"
#include "lowpower/Stm32RtcManager.h"
#include <stm32wle5xx.h>
#include <stm32wlxx_hal.h>

void setBluetoothEnable(bool enable) {}

void playStartMelody() {}

void updateBatteryLevel(uint8_t level) {}

void getMacAddr(uint8_t *dmac)
{
    // https://flit.github.io/2020/06/06/mcu-unique-id-survey.html
    const uint32_t uid0 = HAL_GetUIDw0(); // X/Y coordinate on wafer
    const uint32_t uid1 = HAL_GetUIDw1(); // [31:8] Lot number (23:0), [7:0] Wafer number
    const uint32_t uid2 = HAL_GetUIDw2(); // Lot number (55:24)

    // Need to go from 96-bit to 48-bit unique ID
    dmac[5] = (uint8_t)uid0;
    dmac[4] = (uint8_t)(uid0 >> 16);
    dmac[3] = (uint8_t)uid1;
    dmac[2] = (uint8_t)(uid1 >> 8);
    dmac[1] = (uint8_t)uid2;
    dmac[0] = (uint8_t)(uid2 >> 8);
}

void cpuDeepSleep(uint32_t msecToWake)
{
    if (msecToWake == portMAX_DELAY){
        rtcManager.deepSleepForever();
    }else {
        rtcManager.deepSleep(msecToWake);
    }
    
}

// Hacks to force more code and data out.

// By default __assert_func uses fiprintf which pulls in stdio.
extern "C" void __wrap___assert_func(const char *file, int line, const char *func, const char *expr)
{
#if defined(DRAGINO_BOOT_TRACE)
    Serial.begin(115200);
    Serial.print("[BOOT] ASSERT ");
    Serial.print(file ? file : "?");
    Serial.print(":");
    Serial.print(line);
    Serial.print(" ");
    Serial.print(func ? func : "?");
    Serial.print(" ");
    Serial.println(expr ? expr : "?");
    Serial.flush();
    delay(20);
#else
    (void)file;
    (void)line;
    (void)func;
    (void)expr;
#endif
    while (true)
        ;
    return;
}

// By default strerror has a lot of strings we probably don't use. Make it return an empty string instead.
char empty = 0;
extern "C" char *__wrap_strerror(int)
{
    return &empty;
}

#ifdef MESHTASTIC_EXCLUDE_TZ
struct _reent;

// Even if you don't use timezones, mktime will try to set the timezone anyway with _tzset_unlocked(), which pulls in scanf and
// friends. The timezone is initialized to UTC by default.
extern "C" void __wrap__tzset_unlocked_r(struct _reent *reent_ptr)
{
    return;
}
#endif

#define SEED_MIXED_MODE1
// #define SEED_MIXED_MODE2
// #define SEED_MIXED_MODE3

void stm32wlSetup()
{

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

    HAL_DBGMCU_DisableDBGSleepMode();
    HAL_DBGMCU_DisableDBGStopMode();
    HAL_DBGMCU_DisableDBGStandbyMode();
    
#ifdef BATTERY_PIN
    pinMode(DRAGINO_ADC_HELPER_PIN, INPUT_ANALOG);
#endif

#ifdef STM32WL_RANDOM_SEED_ENABLE
    // Get the unique ID early to use as a random seed and for the device name
    const uint32_t uid0 = HAL_GetUIDw0();
    const uint32_t uid1 = HAL_GetUIDw1();
    const uint32_t uid2 = HAL_GetUIDw2();

    // We want to use the unique ID as part of the random seed, but we also want to mix in some entropy from the RTC if we have it, so we call randomSeed() again after we initialize the RTC.
    uint32_t rtcSubMs = 0;
    uint64_t rtcEpoch = (uint64_t)STM32RTC::getInstance().getEpoch(&rtcSubMs);
    
    // ADC
    uint32_t adcEntropy = 0;
#ifdef BATTERY_PIN
    pinMode(BATTERY_PIN, INPUT_ANALOG);
    analogReadResolution(12);
    for (int i = 0; i < 8; i++) {
        adcEntropy ^= (uint32_t)(analogRead(BATTERY_PIN) & 0x0F) << (i * 4);
    }
#endif
    
    LOG_INFO("Random seed components: uid0=0x%08X uid1=0x%08X uid2=0x%08X rtcEpoch=%lu rtcSubMs=%lu adcEntropy=0x%08X", uid0, uid1, uid2, rtcEpoch, rtcSubMs, adcEntropy);
    
#ifdef  SEED_MIXED_MODE1   
    uint32_t uid_seed = uid0 ^ uid1 ^ uid2;
    uint32_t rtc_seed = (uint32_t)(rtcEpoch ^ (rtcEpoch >> 32)); // ^ rtcSubMs;

    uint32_t mixed_uid = (uid_seed << 16) | (uid_seed >> 16);   
    uint32_t mixed_rtc = (rtc_seed << 8) | (rtc_seed >> 24);    
    uint32_t final_random_seed = mixed_uid ^ mixed_rtc ^ adcEntropy;

#elif defined(SEED_MIXED_MODE2)
    uint32_t final_random_seed = uid0 ^ uid1 ^ uid2 ^ (uint32_t)(rtcEpoch ^ (rtcEpoch >> 32)) ^ rtcSubMs ^ adcEntropy;

#elif defined(SEED_MIXED_MODE3)
    uint32_t final_random_seed = 0;
    final_random_seed ^= (uid0 & 0xFFFF0000) | ((uid0 & 0x0000FFFF) << 16);
    final_random_seed ^= (uid1 & 0xFF00FF00) | ((uid1 & 0x00FF00FF) << 8);
    final_random_seed ^= (uid2 & 0xF0F0F0F0) | ((uid2 & 0x0F0F0F0F) << 4);
    final_random_seed ^= (uint32_t)(rtcEpoch ^ (rtcEpoch >> 32)) ^ rtcSubMs;
    final_random_seed ^= adcEntropy;

#endif

    LOG_INFO("Final random seed: 0x%08X", final_random_seed);
    randomSeed(final_random_seed);

#endif

}














