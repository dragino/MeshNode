/*
Wio-E5 mini (formerly LoRa-E5 mini)
https://www.seeedstudio.com/LoRa-E5-mini-STM32WLE5JC-p-4869.html
https://www.seeedstudio.com/LoRa-E5-Wireless-Module-p-4745.html
*/

/*
This variant is a work in progress.
Do not expect a working Meshtastic device with this target.
*/

#ifndef _VARIANT_DRAGINO_STM32_GATEWAY_
#define _VARIANT_DRAGINO_STM32_GATEWAY_

#define USE_STM32WLx

// #define LED_PIN PB5
// #define LED_STATE_ON 0

#define DRAGINO_STM32_GATEWAY

#define DRAGINO_SD
#ifdef DRAGINO_SD
#define USE_EXTERNAL_FLASH
#define FLASH_CS_PIN   PA4
#endif

#define STM32WL_RANDOM_SEED_ENABLE 1

#endif
