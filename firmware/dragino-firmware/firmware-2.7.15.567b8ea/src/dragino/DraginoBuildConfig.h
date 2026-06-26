#pragma once

#if defined(DRAGINO_GATEWAY) && defined(DRAGINO_REMOTENODE)
#error "Only one of DRAGINO_GATEWAY or DRAGINO_REMOTENODE can be defined"
#endif

#if defined(DRAGINO) && !defined(DRAGINO_GATEWAY) && !defined(DRAGINO_REMOTENODE)
#error "DRAGINO requires DRAGINO_GATEWAY or DRAGINO_REMOTENODE"
#endif

#if defined(DRAGINO_STM32) && defined(DRAGINO_LINUX)
#error "Only one of DRAGINO_STM32 or DRAGINO_LINUX can be defined"
#endif

#if defined(DRAGINO) && !defined(DRAGINO_STM32) && !defined(DRAGINO_LINUX)
#error "DRAGINO requires DRAGINO_STM32 or DRAGINO_LINUX"
#endif
