#pragma once

#include "dragino/protobuf/privateconfig.pb.h"
#include <Arduino.h>

namespace dragino {

class FactoryIdentityManager
{
  public:
    enum class ReadStatus {
        OK,
        EMPTY,
        CRC_ERROR,
        INVALID_FORMAT,
        UNSUPPORTED_PLATFORM,
        WRITE_FAILED,
    };

    static FactoryIdentityManager &instance();

    ReadStatus read(temeshtastic_DeviceFactoryIdentity &identity) const;
    bool load(temeshtastic_DeviceFactoryIdentity &identity) const;
    bool normalize(temeshtastic_DeviceFactoryIdentity &identity) const;
    bool validate(const temeshtastic_DeviceFactoryIdentity &identity) const;
    const char *statusName(ReadStatus status) const;
    void logStorageDiagnostics(ReadStatus status) const;

    bool write(const temeshtastic_DeviceFactoryIdentity &identity);

  private:
    FactoryIdentityManager() = default;
    FactoryIdentityManager(const FactoryIdentityManager &) = delete;
    FactoryIdentityManager &operator=(const FactoryIdentityManager &) = delete;
};

extern FactoryIdentityManager &factoryIdentity;

} // namespace dragino
