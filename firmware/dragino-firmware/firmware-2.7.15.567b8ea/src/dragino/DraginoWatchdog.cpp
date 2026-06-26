#include "DraginoWatchdog.h"

#include "configuration.h"

#if defined(ARCH_STM32WL) && defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32) && DRAGINO_STM32_IWDG_ENABLE
#include <IWatchdog.h>
#include "stm32wlxx_hal_flash.h"
#include "stm32wlxx_hal_flash_ex.h"
#define DRAGINO_WATCHDOG_AVAILABLE 1
#endif

#ifndef DRAGINO_WATCHDOG_AVAILABLE
#define DRAGINO_WATCHDOG_AVAILABLE 0
#endif

#ifndef DRAGINO_STM32_IWDG_EARLY_LOG
#define DRAGINO_STM32_IWDG_EARLY_LOG 0
#endif

#if DRAGINO_STM32_IWDG_EARLY_LOG
#define WD_LOG_INFO(...) LOG_INFO(__VA_ARGS__)
#define WD_LOG_WARN(...) LOG_WARN(__VA_ARGS__)
#define WD_LOG_ERROR(...) LOG_ERROR(__VA_ARGS__)
#else
#define WD_LOG_INFO(...)
#define WD_LOG_WARN(...)
#define WD_LOG_ERROR(...)
#endif

namespace dragino {
namespace watchdog {

#if DRAGINO_WATCHDOG_AVAILABLE
namespace {

bool started = false;
bool resetSeen = false;
uint32_t lastFeedMs = 0;

bool stopFreezeConfigured(const FLASH_OBProgramInitTypeDef &ob)
{
    return ((ob.UserConfig & OB_USER_IWDG_STOP) == OB_IWDG_STOP_FREEZE) &&
           ((ob.UserConfig & OB_USER_IWDG_STDBY) == OB_IWDG_STDBY_FREEZE);
}

bool configureStopFreezeOptionBytesIfNeeded()
{
    FLASH_OBProgramInitTypeDef ob = {};
    ob.WRPArea = OB_WRPAREA_BANK1_AREAA;
    HAL_FLASHEx_OBGetConfig(&ob);

    if (stopFreezeConfigured(ob)) {
        WD_LOG_INFO("IWDG option bytes: STOP/STANDBY freeze already configured");
        return true;
    }

#if DRAGINO_STM32_IWDG_AUTO_CONFIG_OPTION_BYTES
    WD_LOG_WARN("IWDG option bytes: configuring STOP/STANDBY freeze and reloading option bytes");

    FLASH_OBProgramInitTypeDef update = {};
    update.OptionType = OPTIONBYTE_USER;
    update.UserType = OB_USER_IWDG_STOP | OB_USER_IWDG_STDBY;
    update.UserConfig = OB_IWDG_STOP_FREEZE | OB_IWDG_STDBY_FREEZE;

    HAL_StatusTypeDef status = HAL_FLASH_Unlock();
    if (status != HAL_OK) {
        WD_LOG_ERROR("IWDG option bytes: flash unlock failed status=%d", status);
        return false;
    }

    status = HAL_FLASH_OB_Unlock();
    if (status != HAL_OK) {
        WD_LOG_ERROR("IWDG option bytes: OB unlock failed status=%d", status);
        HAL_FLASH_Lock();
        return false;
    }

    __HAL_FLASH_CLEAR_FLAG(FLASH_FLAG_ALL_ERRORS);
    status = HAL_FLASHEx_OBProgram(&update);
    if (status != HAL_OK) {
        WD_LOG_ERROR("IWDG option bytes: OB program failed status=%d err=0x%08x",
                  status,
                  (unsigned)HAL_FLASH_GetError());
        HAL_FLASH_OB_Lock();
        HAL_FLASH_Lock();
        return false;
    }

    feedNow();
    HAL_FLASH_OB_Launch();
    HAL_FLASH_OB_Lock();
    HAL_FLASH_Lock();
    return false;
#else
    WD_LOG_WARN("IWDG option bytes: STOP/STANDBY freeze not configured");
    return false;
#endif
}

} // namespace
#endif

bool enabled()
{
#if DRAGINO_WATCHDOG_AVAILABLE
    return started;
#else
    return false;
#endif
}

bool wasReset()
{
#if DRAGINO_WATCHDOG_AVAILABLE
    return resetSeen;
#else
    return false;
#endif
}

void beginEarly()
{
#if DRAGINO_WATCHDOG_AVAILABLE
    if (started) {
        feedNow();
        return;
    }

    resetSeen = IWatchdog.isReset(false);
    IWatchdog.begin(DRAGINO_STM32_IWDG_TIMEOUT_US);
    started = IWatchdog.isEnabled();
    feedNow();

#if DRAGINO_STM32_IWDG_SLEEP_MODE == DRAGINO_STM32_IWDG_SLEEP_FREEZE
    configureStopFreezeOptionBytesIfNeeded();
    feedNow();
#endif

    if (started) {
        WD_LOG_INFO("IWDG enabled timeout=%luus feedInterval=%lums resetSeen=%d",
                 (unsigned long)DRAGINO_STM32_IWDG_TIMEOUT_US,
                 (unsigned long)DRAGINO_STM32_IWDG_FEED_INTERVAL_MS,
                 resetSeen ? 1 : 0);
    } else {
        WD_LOG_ERROR("IWDG begin failed timeout=%luus", (unsigned long)DRAGINO_STM32_IWDG_TIMEOUT_US);
    }
#endif
}

void feed()
{
#if DRAGINO_WATCHDOG_AVAILABLE
    if (!started) {
        return;
    }

    const uint32_t now = millis();
    if ((uint32_t)(now - lastFeedMs) >= DRAGINO_STM32_IWDG_FEED_INTERVAL_MS) {
        feedNow();
    }
#endif
}

void feedNow()
{
#if DRAGINO_WATCHDOG_AVAILABLE
    IWatchdog.reload();
    lastFeedMs = millis();
#endif
}

void prepareForSleep()
{
#if DRAGINO_WATCHDOG_AVAILABLE
    if (!started) {
        return;
    }

    feedNow();
#endif
}

void afterStopWake()
{
#if DRAGINO_WATCHDOG_AVAILABLE
    if (!started) {
        return;
    }

    feedNow();
#endif
}

bool stopFreezeOptionBytesOk()
{
#if DRAGINO_WATCHDOG_AVAILABLE
    FLASH_OBProgramInitTypeDef ob = {};
    ob.WRPArea = OB_WRPAREA_BANK1_AREAA;
    HAL_FLASHEx_OBGetConfig(&ob);
    return stopFreezeConfigured(ob);
#else
    return true;
#endif
}

} // namespace watchdog
} // namespace dragino
