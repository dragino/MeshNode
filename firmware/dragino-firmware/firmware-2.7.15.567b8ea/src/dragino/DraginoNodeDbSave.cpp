#include "configuration.h"

#if defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)

#include "DraginoNodeDbSave.h"

namespace dragino {

static bool nodeDbSavePending = false;

void markNodeDbSavePending()
{
    nodeDbSavePending = true;
}

bool isNodeDbSavePending()
{
    return nodeDbSavePending;
}

void clearNodeDbSavePending()
{
    nodeDbSavePending = false;
}

} // namespace dragino

#endif // defined(DRAGINO_REMOTENODE) && defined(DRAGINO_STM32)
