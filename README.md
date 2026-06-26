# MeshNode

MeshNode contains Dragino's MeshNode firmware and related debugging tools.

The firmware in this repository is based on Meshtastic firmware 2.7.15 and includes Dragino-specific changes for STM32WL MeshNode devices, private configuration, factory identity, wakeup behavior, and board variants.

## Repository Layout

```text
firmware/
  dragino-firmware/
    firmware-2.7.15.567b8ea/  Dragino firmware fork based on Meshtastic 2.7.15

apps/
  meshdebug/                  MeshDebug desktop tool for debugging MeshNode devices
```

## Firmware

The firmware fork keeps the original Meshtastic project structure and adds Dragino-specific code under areas such as:

- `src/dragino/`
- `src/platform/stm32wl/`
- `variants/stm32/dragino-*`
- `variants/native/dragino-linux-gateway/`

Build artifacts, PlatformIO output, local assistant files, and the large firmware documentation bundle are intentionally ignored.

## MeshDebug

`apps/meshdebug` is a Python/PyQt debugging tool for Meshtastic-compatible Dragino MeshNode devices.

It can inspect and send MeshNode/Meshtastic packets, handle Dragino private configuration payloads, and help validate factory identity, join, wakeup, and diagnostic workflows.

See [apps/meshdebug/README.md](apps/meshdebug/README.md) for setup, run, and test commands.

Local device credentials and runtime settings are ignored and should not be committed.

## License

This repository includes software derived from Meshtastic firmware and software that depends on the Meshtastic Python package. These components are distributed under the GNU General Public License v3.0.

See [LICENSE](LICENSE) for the full license text.
