# Harkenn flash

Two small things for [Harkenn](https://github.com/harkenn-project/server-docker), the private voice assistant for
your home, in one service:

- **The web flasher.** Installs the [speaker firmware](https://github.com/harkenn-project/speaker-firmware) on a
  speaker straight from the browser, over USB. No tools to install.
- **The relay.** Lets a speaker that's away from home (at a friend's, on holiday) keep talking to its Harkenn server,
  which usually lives on a home network the speaker can't reach.

It runs at [flash.mylife.ninja](https://flash.mylife.ninja); you can run your own.

## The flasher

Open the page in Chrome or Edge on a computer, plug the speaker in with a USB-C data cable, pick a release channel
and press **Connect and check the speaker**. Before it writes anything, the page checks that the board really is a
Harkenn speaker (a Spotpear ESP32-S3 1.28" BOX):

- the chip is an **ESP32-S3**,
- it has **8 MB of embedded PSRAM**,
- it has **16 MB of flash**.

Any other board is refused untouched. The page then downloads the release's install image (bootloader, partition
table and app, published on speaker-firmware's `releases` branch), checks its size and SHA-256, erases the speaker and
writes it. The speaker restarts into its Wi-Fi setup.

Installing erases the speaker, including the XiaoZhi firmware it ships with: back that up first if you might want it.

## The relay

A speaker set up for remote connection (on its page in Harkenn) that can't find its server for two minutes connects
to the relay instead; while it's offline there, its Harkenn server connects to the relay too. The relay pairs the two
by the speaker's random relay id and passes their frames along.

It can't read or change them: everything between the speaker and Harkenn is encrypted with a key only they have
(an HMAC handshake, then AES-256-GCM with counters each way). The relay sees which ids connect, from where, when, and
how much they send; not the speaker's token, its name, or anything said. The protocol is in
[RELAY.md](https://github.com/harkenn-project/server-docker/blob/main/docs/RELAY.md).

Limits: 500 pairings at once and 20 connections per address (`FLASH_MAX_RELAYS`, `FLASH_MAX_PER_IP`), frames of at
most 1 MB.

## Endpoints

| Path | |
|---|---|
| `/` | The flasher page |
| `/release/<channel>.json` | The newest install image on `stable`, `beta`, `alpha` or `development`: `{version, hardware, url, size, sha256}` |
| `/relay/speaker/<id>` | WebSocket: a speaker away from home (`<id>` is 32 hex digits) |
| `/relay/harkenn/<id>` | WebSocket: its Harkenn server |
| `/healthz` | `ok` |

## Run it

```
docker run -p 8000:8000 ghcr.io/harkenn-project/flash:latest
```

The flasher needs https (browsers only allow USB access from secure pages), so put it behind a TLS proxy or tunnel.
WebSockets must pass through, and stay open: the server pings every 30 s, which keeps idle connections alive through
Cloudflare. One replica: pairings are held in memory.

Point Harkenn at it with `HARKENN_RELAY_URL` (as speakers reach it, e.g. `wss://flash.example.com`) and, if Harkenn
reaches it another way, `HARKENN_RELAY_SERVER_URL`.

| Variable | Default | |
|---|---|---|
| `FLASH_RELEASES_URL` | speaker-firmware's `releases` branch on GitHub | Where `latest*.json` and the install images are |
| `FLASH_MAX_RELAYS` | `500` | Pairings at once |
| `FLASH_MAX_PER_IP` | `20` | Connections per address |

## Develop

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\uvicorn --factory app.main:create_app --port 8000
.venv\Scripts\pytest -q
```

The Jenkins job that tests, builds and pushes the image is defined in [jenkins/build-image.xml](jenkins/build-image.xml).

## Credits

Built on esptool-js, Starlette and Uvicorn: see [CREDITS.md](CREDITS.md).

Created by **Master Magic** and **Pip**, Master Magic's AI apprentice, with the Harkenn contributors. Pip is the name
we give the AI assistant that co-writes Harkenn.

## Licence

[MIT](LICENSE), copyright the Harkenn contributors. Third-party components keep their own licences (see
[CREDITS.md](CREDITS.md)).
