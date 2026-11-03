"""flash.mylife.ninja: the Harkenn speaker web flasher, and the relay for speakers that can't reach their server.

The flasher (/) installs speaker firmware over USB from the browser (esptool-js), with the install images that
speaker-firmware publishes on its releases branch. It checks the board first (an ESP32-S3 with 8 MB of PSRAM and
16 MB of flash) and the image's SHA-256, and won't write anything to a board that isn't a Harkenn speaker.

The relay (/relay/...) is not advertised. A speaker that can't reach its Harkenn server, and was set up for remote
connection, connects to /relay/speaker/<id>; its Harkenn server connects to /relay/harkenn/<id> while the speaker is
offline there. The relay pairs the two by id and passes their frames through untouched. What they send is end-to-end
encrypted with a key the relay never sees (docs/RELAY.md in server-docker), so the relay can't read or alter it,
and the id only lets someone take part in a pairing, not understand it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import urllib.request
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket

log = logging.getLogger("harkenn.flash")

STATIC = Path(__file__).parent / "static"
RELEASES = os.environ.get("FLASH_RELEASES_URL",
                          "https://raw.githubusercontent.com/harkenn-project/speaker-firmware/releases").rstrip("/")
CHANNELS = {"stable": "latest.json", "beta": "latest-beta.json", "alpha": "latest-alpha.json",
            "development": "latest-development.json"}
RELEASE_CACHE_S = 300
RELAY_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_FRAME = 1024 * 1024  # a frame is at most a chunk of speech, a fetched file or a screen's picture
MAX_SLOTS = int(os.environ.get("FLASH_MAX_RELAYS", "500"))
MAX_PER_IP = int(os.environ.get("FLASH_MAX_PER_IP", "20"))
SIDES = ("speaker", "harkenn")


# the flasher

_manifests: dict[str, tuple[float, dict]] = {}


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read(64 * 1024))


async def release(request: Request) -> Response:
    """The newest install image on a release channel: where it is, its size and SHA-256 (the page checks both)."""
    channel = request.path_params["channel"]
    if channel not in CHANNELS:
        return PlainTextResponse("unknown channel", status_code=404)
    cached = _manifests.get(channel)
    if not cached or time.time() - cached[0] > RELEASE_CACHE_S:
        try:
            found = await run_in_threadpool(_get_json, f"{RELEASES}/{CHANNELS[channel]}")
        except Exception as e:  # GitHub down: an older answer is better than none
            if not cached:
                return PlainTextResponse(f"couldn't read the releases: {e}", status_code=502)
            log.warning("releases: %s (using the cached answer)", e)
        else:
            install = found.get("install")
            if not install:
                return PlainTextResponse(f"no install image on the {channel} channel yet", status_code=404)
            cached = (time.time(), {
                "version": found["version"],
                "hardware": found.get("hardware", ""),
                "url": f"{RELEASES}/{install['file']}",
                "size": install["size"],
                "sha256": install["sha256"],
            })
            _manifests[channel] = cached
    return JSONResponse(cached[1], headers={"Cache-Control": "no-cache"})


async def index(request: Request) -> Response:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


async def healthz(request: Request) -> Response:
    return PlainTextResponse("ok")


# the relay

@dataclass
class Slot:
    sockets: dict[str, WebSocket] = field(default_factory=dict)
    paired: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Event = field(default_factory=asyncio.Event)


class Relay:
    def __init__(self) -> None:
        self.slots: dict[str, Slot] = {}
        self.per_ip: dict[str, int] = {}

    def stats(self) -> dict[str, int]:
        return {"waiting": sum(1 for s in self.slots.values() if not s.paired.is_set()),
                "paired": sum(1 for s in self.slots.values() if s.paired.is_set())}

    async def serve(self, ws: WebSocket, side: str, rid: str) -> None:
        ip = ws.client.host if ws.client else "?"
        if not RELAY_ID.match(rid):
            await ws.close(code=4404)
            return
        if (rid not in self.slots and len(self.slots) >= MAX_SLOTS) or self.per_ip.get(ip, 0) >= MAX_PER_IP:
            await ws.close(code=4429)
            return
        await ws.accept()
        self.per_ip[ip] = self.per_ip.get(ip, 0) + 1
        slot = self.slots.get(rid)
        if slot is None or slot.done.is_set():
            slot = self.slots[rid] = Slot()
        old = slot.sockets.get(side)
        if old is not None:  # the same side again (it reconnected): the newer one wins
            with suppress(Exception):
                await old.close(code=4000)
        slot.sockets[side] = ws
        log.info("%s %s… connected from %s", side, rid[:6], ip)
        try:
            other = "harkenn" if side == "speaker" else "speaker"
            if other in slot.sockets and not slot.paired.is_set():
                slot.paired.set()
                for s in SIDES:
                    await slot.sockets[s].send_text('{"type":"paired"}')
                log.info("paired %s…", rid[:6])
            await self._pump(ws, slot, side)
        finally:
            self.per_ip[ip] -= 1
            if not self.per_ip[ip]:
                del self.per_ip[ip]
            if slot.sockets.get(side) is ws:
                del slot.sockets[side]
                if slot.paired.is_set():  # one side left: end the pairing, both start over
                    slot.done.set()
                    for s in list(slot.sockets.values()):
                        with suppress(Exception):
                            await s.close(code=4001)
                if not slot.sockets and self.slots.get(rid) is slot:
                    del self.slots[rid]
            log.info("%s %s… gone", side, rid[:6])

    async def _pump(self, ws: WebSocket, slot: Slot, side: str) -> None:
        """Pass this side's frames to the other once paired; before that, there's nobody to hear them."""
        other = "harkenn" if side == "speaker" else "speaker"
        while True:
            frame = await ws.receive()
            if frame["type"] == "websocket.disconnect":
                return
            data = frame.get("bytes")
            if data is None:
                continue  # only binary frames are relayed; text is the relay's own ("paired")
            if len(data) > MAX_FRAME:
                await ws.close(code=1009)
                return
            peer = slot.sockets.get(other) if slot.paired.is_set() else None
            if peer is not None:
                try:
                    await peer.send_bytes(data)
                except Exception:
                    return


relay = Relay()


async def relay_speaker(ws: WebSocket) -> None:
    await relay.serve(ws, "speaker", ws.path_params["rid"])


async def relay_harkenn(ws: WebSocket) -> None:
    await relay.serve(ws, "harkenn", ws.path_params["rid"])


def create_app() -> Starlette:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return Starlette(routes=[
        Route("/", index),
        Route("/release/{channel}.json", release),
        Route("/healthz", healthz),
        WebSocketRoute("/relay/speaker/{rid}", relay_speaker),
        WebSocketRoute("/relay/harkenn/{rid}", relay_harkenn),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ])
