/**
 * Stm32wlLowPower.c - STM32WL preparation before entering STOP2.
 *
 * This addresses the 2 mA sleep-current issue seen on STM32WL with
 * Meshtastic. The root cause is that the Arduino LowPower_stop() path does
 * not stop SysTick. A pending SysTick interrupt can make WFI return
 * immediately, so the CPU never really enters STOP2.
 *
 * The reference STM32 low-power flow does:
 *   HAL_SuspendTick();
 *   LL_PWR_ClearFlag_C1STOP_C1STB();
 *   HAL_PWREx_EnterSTOP2Mode(PWR_STOPENTRY_WFI);
 * Meshtastic's LowPower_stop() path is missing the first two steps.
 */

#include "Stm32wlLowPower.h"
#include <stm32wlxx_hal.h>
#include <stm32wlxx_ll_pwr.h>

/*
 * Shut down the internal LoRa peripheral clock and IRQ.
 *
 * STM32WLE integrates the LoRa radio on-chip; it is not an external SPI
 * device. ST still names the internal bus SUBGHZSPI and exposes its clock as
 * SUBGHZSPI_CLK, so "SPI" here is just ST naming. This disables the internal
 * radio clock domain.
 *
 * RadioLib already puts the radio into sleep mode through
 * SX126xInterface::sleep() from the notifyDeepSleep callback. This function
 * also gates the peripheral clock and IRQ to avoid residual clock-domain
 * leakage, matching the HAL_SUBGHZ_MspDeInit() approach used by the reference
 * STM32 project.
 */
void lp_shutdown_radio(void)
{
    __HAL_RCC_SUBGHZSPI_CLK_DISABLE();
    HAL_NVIC_DisableIRQ(SUBGHZ_Radio_IRQn);
}

/*
 * Make WFI really enter STOP2.
 *
 * On ARM Cortex-M, WFI returns immediately if any interrupt is pending, so the
 * CPU does not enter sleep. Arduino SysTick fires every 1 ms and keeps setting
 * the pending bit. Before WFI we must:
 *   1. Stop SysTick so no new pending bits are generated.
 *   2. Clear the SysTick pending bit.
 *   3. Clear all pending NVIC interrupts.
 *   4. Clear the PWR STOP/STANDBY flags.
 */
void lp_prepare_stop2(void)
{
    HAL_SuspendTick();

    SCB->ICSR |= SCB_ICSR_PENDSTCLR_Msk;

    for (uint32_t i = 0; i < sizeof(NVIC->ICPR) / sizeof(NVIC->ICPR[0]); i++) {
        NVIC->ICPR[i] = 0xFFFFFFFF;
    }

    LL_PWR_ClearFlag_C1STOP_C1STB();
}

/*
 * Disable debug clocks.
 *
 * DBGMCU keeps debug clocks running in Sleep/Stop/Standby by default, which
 * can add roughly 1-2 mA. The debugger disconnects after this is disabled.
 */
void lp_disable_debug(void)
{
    HAL_DBGMCU_DisableDBGSleepMode();
    HAL_DBGMCU_DisableDBGStopMode();
    HAL_DBGMCU_DisableDBGStandbyMode();
}

/*
 * Run the full preparation sequence before LowPower.deepSleep().
 */
void lp_prepare_all(void)
{
    lp_shutdown_radio();
    lp_disable_debug();
    lp_prepare_stop2();  // Keep this last because it stops SysTick.
}

void lp_resume_subghz(void)
{
    __HAL_RCC_SUBGHZSPI_CLK_ENABLE();
    HAL_NVIC_ClearPendingIRQ(SUBGHZ_Radio_IRQn);
    HAL_NVIC_EnableIRQ(SUBGHZ_Radio_IRQn);
}

void lp_resume_after_stop2_core(void)
{
    HAL_ResumeTick();
    SCB->ICSR |= SCB_ICSR_PENDSTCLR_Msk;

    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();
#ifdef GPIOD
    __HAL_RCC_GPIOD_CLK_ENABLE();
#endif
#ifdef GPIOE
    __HAL_RCC_GPIOE_CLK_ENABLE();
#endif
}

void lp_resume_after_stop2(void)
{
    lp_resume_after_stop2_core();
    lp_resume_subghz();
}

void lp_compensate_hal_tick(uint32_t slept_ms)
{
    extern __IO uint32_t uwTick;

    if (slept_ms == 0) {
        return;
    }

    uwTick += slept_ms;
}

/*
 * Bypass the Arduino LowPower library and enter STOP2 directly through HAL.
 * This sleeps forever.
 *
 * Temporarily replace LowPower.deepSleep(ms) in Stm32RtcManager::deepSleep()
 * with lp_raw_stop2_forever() for diagnostics.
 *
 * This mirrors the reference STM32 low-power flow:
 *   - Put all GPIOs into analog mode.
 *   - Disable all peripheral clocks.
 *   - HAL_SuspendTick and clear interrupts.
 *   - Enter HAL_PWREx_EnterSTOP2Mode directly.
 *
 * There is no wake source, so the device sleeps forever and can only exit by
 * reset or reflashing. Use this for current measurements to confirm whether
 * the hardware can reach the uA range.
 */
void lp_raw_stop2_forever(void)
{
    __disable_irq();

    /* Disable all peripheral clocks. */
    __HAL_RCC_SUBGHZSPI_CLK_DISABLE();
    HAL_NVIC_DisableIRQ(SUBGHZ_Radio_IRQn);

    /* Disable debug. */
    HAL_DBGMCU_DisableDBGSleepMode();
    HAL_DBGMCU_DisableDBGStopMode();
    HAL_DBGMCU_DisableDBGStandbyMode();

    /* Put all GPIO pins into analog mode. */
    GPIO_InitTypeDef gpio = {0};
    gpio.Mode  = GPIO_MODE_ANALOG;
    gpio.Pull  = GPIO_NOPULL;
    gpio.Speed = GPIO_SPEED_FREQ_LOW;
    gpio.Pin   = GPIO_PIN_All;

    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();
    HAL_GPIO_Init(GPIOA, &gpio);
    HAL_GPIO_Init(GPIOB, &gpio);
    HAL_GPIO_Init(GPIOC, &gpio);
    __HAL_RCC_GPIOA_CLK_DISABLE();
    __HAL_RCC_GPIOB_CLK_DISABLE();
    __HAL_RCC_GPIOC_CLK_DISABLE();

    /* Stop SysTick and clear all pending interrupts. */
    HAL_SuspendTick();
    SCB->ICSR |= SCB_ICSR_PENDSTCLR_Msk;
    for (uint32_t i = 0; i < sizeof(NVIC->ICPR) / sizeof(NVIC->ICPR[0]); i++) {
        NVIC->ICPR[i] = 0xFFFFFFFF;
    }
    LL_PWR_ClearFlag_C1STOP_C1STB();

    /* Enter STOP2 directly, matching the reference flow. */
    HAL_PWREx_EnterSTOP2Mode(PWR_STOPENTRY_WFI);

    /* This should not return; reset if it does. */
    NVIC_SystemReset();
}
