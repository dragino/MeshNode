#pragma once

#include <stdint.h>

/**
 * Stm32wlLowPower.h - STM32WL preparation before entering STOP2.
 *
 * Call the helper functions as needed, or call lp_prepare_all() to run the
 * full preparation sequence.
 */

#ifdef __cplusplus
extern "C" {
#endif

/// Shut down the internal LoRa peripheral clock and IRQ after RadioLib has put the radio to sleep.
void lp_shutdown_radio(void);

/// Stop SysTick, clear pending IRQs and PWR flags so WFI can really enter STOP2.
void lp_prepare_stop2(void);

/// Disable debug clocks to avoid DBGMCU leakage in low-power modes.
void lp_disable_debug(void);

/// Run the full STOP2 preparation sequence.
void lp_prepare_all(void);

/// Restore platform clocks/interrupts that were explicitly disabled before STOP2.
void lp_resume_after_stop2_core(void);

/// Restore platform clocks/interrupts and the STM32WL internal LoRa gate.
void lp_resume_after_stop2(void);

/// Restore the STM32WL internal LoRa bus clock/IRQ gate before RadioLib reconfigure().
void lp_resume_subghz(void);

/// Advance HAL/Arduino millis() by the time spent while SysTick was stopped.
void lp_compensate_hal_tick(uint32_t slept_ms);

/// Bypass the Arduino LowPower library and enter STOP2 directly through HAL.
/// This sleeps forever and is intended for current-consumption diagnostics.
/// If current drops to the uA range, the issue is in the Arduino LowPower path.
/// If it stays near 2 mA, the issue is likely external hardware.
void lp_raw_stop2_forever(void);

#ifdef __cplusplus
}
#endif
