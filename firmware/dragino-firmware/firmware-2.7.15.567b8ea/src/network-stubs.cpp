#include "configuration.h"

#if defined(ARCH_PORTDUINO)
#include <WiFi.h>

bool initWifi()
{
    return WiFi.isConnected();
}

void deinitWifi() {}

bool isWifiAvailable()
{
    return WiFi.isConnected();
}

uint8_t getWifiDisconnectReason()
{
    return 0;
}

#elif (HAS_WIFI == 0)

bool initWifi()
{
    return false;
}

void deinitWifi() {}

bool isWifiAvailable()
{
    return false;
}

#endif

#if (HAS_ETHERNET == 0)

bool initEthernet()
{
    return false;
}

bool isEthernetAvailable()
{
    return false;
}

#endif
