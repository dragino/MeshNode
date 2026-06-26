# MeshDebug

MeshDebug is a Dragino debugging tool for Meshtastic-compatible MeshNode devices.

It depends on the Meshtastic Python package and protobuf definitions. Because the Meshtastic Python package is licensed under GPL-3.0-only, this tool is distributed under the GNU General Public License v3.0. See the repository root [LICENSE](../../LICENSE) file for the full license text.

## Setup

```powershell
cd apps\meshdebug
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

## Run

```powershell
cd apps\meshdebug
.\.venv\Scripts\python main.py
```

## Test

```powershell
cd apps\meshdebug
.\.venv\Scripts\python -m unittest discover -s tests
```

## Local Data

Do not commit local runtime data or device credentials. The following files are ignored intentionally:

- `meshdebug_settings.json`
- `virtual_identity.json`
- `factory_identity_profiles.json`
- `.venv/`
- `.idea/`
