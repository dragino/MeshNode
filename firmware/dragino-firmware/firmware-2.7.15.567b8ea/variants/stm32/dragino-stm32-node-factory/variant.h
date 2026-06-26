/*
Wio-E5 mini (formerly LoRa-E5 mini)
https://www.seeedstudio.com/LoRa-E5-mini-STM32WLE5JC-p-4869.html
https://www.seeedstudio.com/LoRa-E5-Wireless-Module-p-4745.html
*/

/*
This variant is a work in progress.
Do not expect a working Meshtastic device with this target.
*/

#ifndef _VARIANT_DRAGINO_STM32_NODE_
#define _VARIANT_DRAGINO_STM32_NODE_

#define USE_STM32WLx

// #define LED_PIN PB5
// #define LED_STATE_ON 0

#define DRAGINO_STM32_NODE

#if (defined(LED_BUILTIN) && LED_BUILTIN == PNUM_NOT_DEFINED)
#undef LED_BUILTIN
#define LED_BUILTIN (LED_PIN)
#endif


#define DRAGINO_SD
#ifdef DRAGINO_SD
#define USE_EXTERNAL_FLASH
#define FLASH_CS_PIN   PA4
#endif

#define WAKEUP_BUTTON_PIN PA8
#define EXTERNAL_SENSOR_CONTROL_PIN PA0



#define ADC_BATTERY_ENABLE 1
#ifdef ADC_BATTERY_ENABLE
#define BATTERY_PIN PA15
#define ADC_MULTIPLIER 6.24f
#define BATTERY_SENSE_RESOLUTION_BITS 12
#define OCV_ARRAY 3900, 3840, 3780, 3700, 3600, 3480, 3350, 3200, 3050, 2880, 2700
#endif


// Dragino external voltage ADC
// #define DRAGINO_ENABLE_EXTERNAL_ADC        1
#define DRAGINO_ADC_EXTERNAL_PIN           PA15
#define DRAGINO_ADC_HELPER_PIN             PA14
#define DRAGINO_ADC_SAMPLES                10
#define DRAGINO_ADC_INTERVAL_MS            5000
#define DRAGINO_ADC_EXTERNAL_MULTIPLIER    6.24f
#define DRAGINO_ADC_VREF_MV                3300
#define DRAGINO_ADC_MAX_VALUE              4095



#define STM32WL_RANDOM_SEED_ENABLE 1



// DX-BT24 Bluetooth module control pins
#define DRAGINO_BT_LINK_PIN  PC4     // Input:  HIGH = BLE connected
#define DRAGINO_BT_WORK_PIN  PC1     // Input:  work status indicator
#define DRAGINO_BT_KEY_PIN   PC5     // Output: low pulse for disconnect/wakeup/pair
#define DRAGINO_BT_RST_PIN   PB8     // Output: low >=200ms for hard reset / hibernate wakeup








#endif
