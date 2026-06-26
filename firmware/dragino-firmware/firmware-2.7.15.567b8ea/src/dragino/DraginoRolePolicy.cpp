#include "DraginoRolePolicy.h"

#include "DraginoBuildConfig.h"

#if defined(DRAGINO_REMOTENODE)
#include "PrivateConfig.h"
#include "configuration.h"
#include "mesh/NodeDB.h"
#include "mesh/TypeConversions.h"
#include <string.h>
#endif

namespace dragino {

#if defined(DRAGINO_REMOTENODE)
namespace {

const char *roleName(meshtastic_Config_DeviceConfig_Role role)
{
    switch (role) {
    case meshtastic_Config_DeviceConfig_Role_CLIENT:
        return "CLIENT";
    case meshtastic_Config_DeviceConfig_Role_CLIENT_MUTE:
        return "CLIENT_MUTE";
    default:
        return "OTHER";
    }
}

meshtastic_Config_DeviceConfig_Role expectedRoleForEnrollment()
{
    return privateConfig.isEnrolled()
               ? meshtastic_Config_DeviceConfig_Role_CLIENT
               : meshtastic_Config_DeviceConfig_Role_CLIENT_MUTE;
}

bool syncLocalNodeUser()
{
    if (!nodeDB) {
        LOG_WARN("DraginoRolePolicy: NodeDB unavailable, skip local node sync");
        return false;
    }

    meshtastic_NodeInfoLite *localNode = nodeDB->getMeshNode(nodeDB->getNodeNum());
    if (!localNode) {
        LOG_WARN("DraginoRolePolicy: local node unavailable, skip local node sync");
        return false;
    }

    const auto ownerLite = TypeConversions::ConvertToUserLite(owner);
    if (localNode->has_user && memcmp(&localNode->user, &ownerLite, sizeof(localNode->user)) == 0) {
        return false;
    }

    localNode->user = ownerLite;
    localNode->has_user = true;
    nodeDB->updateGUIforNode = localNode;
    nodeDB->notifyObservers(true);
    return true;
}

} // namespace
#endif

int applyRemoteNodeEnrollmentRolePolicy(const char *reason)
{
#if defined(DRAGINO_REMOTENODE)
    const bool enrolled = privateConfig.isEnrolled();
    const auto targetRole = expectedRoleForEnrollment();
    const auto oldConfigRole = config.device.role;
    const auto oldOwnerRole = owner.role;
    int saveMask = 0;

    if (config.device.role != targetRole) {
        config.device.role = targetRole;
        saveMask |= SEGMENT_CONFIG;
    }

    if (owner.role != targetRole) {
        owner.role = targetRole;
        saveMask |= SEGMENT_DEVICESTATE;
    }

    if (syncLocalNodeUser()) {
        saveMask |= SEGMENT_NODEDATABASE;
    }

    if (saveMask) {
        LOG_INFO("DraginoRolePolicy: reason=%s enrolled=%d role %s/%s -> %s saveMask=%d",
                 reason ? reason : "unknown",
                 enrolled,
                 roleName(oldConfigRole),
                 roleName(oldOwnerRole),
                 roleName(targetRole),
                 saveMask);
    } else {
        LOG_DEBUG("DraginoRolePolicy: reason=%s enrolled=%d no change role=%s",
                  reason ? reason : "unknown",
                  enrolled,
                  roleName(targetRole));
    }

    return saveMask;
#else
    (void)reason;
    return 0;
#endif
}

bool applyAndSaveRemoteNodeEnrollmentRolePolicy(const char *reason)
{
    const int saveMask = applyRemoteNodeEnrollmentRolePolicy(reason);
    if (!saveMask) {
        return true;
    }

#if defined(DRAGINO_REMOTENODE)
    if (!nodeDB) {
        LOG_WARN("DraginoRolePolicy: NodeDB unavailable, cannot save role policy");
        return false;
    }

    return nodeDB->saveToDisk(saveMask);
#else
    return true;
#endif
}

} // namespace dragino
