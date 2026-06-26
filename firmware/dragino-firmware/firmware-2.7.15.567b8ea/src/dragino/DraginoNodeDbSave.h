#pragma once

#include "configuration.h"

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)

namespace dragino {

void markNodeDbSavePending();
bool isNodeDbSavePending();
void clearNodeDbSavePending();

} // namespace dragino

#endif // defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
