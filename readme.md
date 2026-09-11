# ha-keepsmile
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

Home Assistant integration for KeepSmile BLE lights (`KS03~` family, e.g. `KS03~981B2B`).

The protocol was reverse-engineered from the official KeepSmile Android app
(`com.youzda.smartlight` v1.1) and verified live: single GATT service `AFD0`,
write on `AFD1`, status notifications on `AFD2`.

## Installation

Note: Restart is always required after installation.

### [HACS](https://hacs.xyz/) (recommended)
Installation can be done through [HACS custom repository](https://hacs.xyz/docs/faq/custom_repositories).

### Manual installation
You can manually clone this repository inside `config/custom_components/keepsmile`.

For example, from Terminal plugin:
```
cd /config/custom_components
git clone https://github.com/HazWard/ha-keepsmile keepsmile
```

## Setup
After installation, you should find KeepSmile under Configuration -> Integrations -> Add integration.

The setup step includes discovery which will list out all KeepSmile lights discovered. The setup will validate connection by toggling the selected light. Make sure your light is in-sight to validate this.

The setup needs to be repeated for each light.

## Features
1. Discovery: Automatically discover KeepSmile based lights without manually hunting for Bluetooth MAC address
2. On/Off/RGB/White/Brightness support (RGB + white color modes)
3. Optimistic state tracking: commands apply instantly in Home Assistant
4. Live state polling: a status query is sent on every poll; confirmed reports update Home Assistant
5. Multiple light support

## Protocol notes
- Frames: `ON 5B F0 <channel> B5`, `OFF 5B 0F <channel> B5`,
  `RGB 5A 00 01 RR GG BB 00 BR 00 A5`, `White 5A 00 01 FF FF FF 00 BR 00 A5`.
- Brightness is 0-100 on the wire (percent, as in the app) and scaled to/from Home Assistant's 0-255.
- A full-white RGB pick (`255, 255, 255`) drives the native white frame.
- The peripheral drops idle BLE connections after ~1-2 s, so every operation reconnects on demand.

## Known issues
1. The `5F 01 00 F5` status query is answered with a 12-byte `5F ... F5` frame whose field layout is not decoded yet, so polls confirm reachability but rarely refresh color/brightness. State therefore follows the last command until the layout is decoded.
2. Light connection may fail a few times after Home Assistant reboot. The integration will usually reconnect and the issue will resolve itself.

## Debugging
Add the following to `configuration.yml` to show debugging logs. Please make sure to include debug logs when filing an issue.

See [logger intergration docs](https://www.home-assistant.io/integrations/logger/) for more information to configure logging.

```yml
logger:
  default: warn
  logs:
    custom_components.keepsmile: debug
```

## Credits
This integration started as a fork of the keepsimple/Triones BLE integration and was reworked for the `KS03~` protocol family. Protocol details came from disassembling the official KeepSmile app.
