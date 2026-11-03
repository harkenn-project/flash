# Credits

Harkenn flash is built on these open-source projects. Thank you to all of them.

| Project | Used for | Licence |
|---|---|---|
| [esptool-js](https://github.com/espressif/esptool-js) (Espressif) | Talking to the speaker over USB from the browser: checking the board and writing the firmware. Loaded by the flasher page from [unpkg](https://unpkg.com) | Apache-2.0 |
| [Starlette](https://github.com/Kludex/starlette) | Web framework: the flasher page, release info and the relay's WebSockets | BSD-3-Clause |
| [Uvicorn](https://github.com/encode/uvicorn) | Web server | BSD-3-Clause |
| [Python](https://www.python.org) | Everything on the server side | PSF |
| [Web Serial API](https://wicg.github.io/serial/) (Chrome, Edge) | The browser's way to the USB port | standard |

The firmware the flasher installs is [speaker-firmware](https://github.com/harkenn-project/speaker-firmware); its own
credits are in its [CREDITS.md](https://github.com/harkenn-project/speaker-firmware/blob/main/CREDITS.md).
