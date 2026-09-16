"""
How mc_sessions reaches the Minecraft server.

ZymBot runs in its own Pterodactyl container, so the Minecraft server's files and console are not on
this machine as far as the bot can tell, and localhost is the container rather than the host. There
are two ways in, because neither does both jobs:

  * Server List Ping - the request the multiplayer screen makes. Player count and names, with no
    config on the server and no password.
  * The Pterodactyl client API - power state, console commands and file reads.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import struct
from dataclasses import dataclass, field

import aiohttp

# 1.21.1. A status request is answered whatever protocol is sent; this only changes whether the
# server reports itself as compatible.
PROTOCOL_VERSION = 767

MINECRAFT_NAME = re.compile(r"^[A-Za-z0-9_]{3,16}$")

# A join as the server logs it: "[14:02:11] [Server thread/INFO]: ZymSB joined the game".
# Anchored on the logger prefix so chat cannot forge one - a chat line has "<name>" straight after the
# colon, and the name group does not allow "<".
JOIN_LINE = re.compile(
    r"^\[[^\]\n]+\] \[Server thread/INFO\](?: \[[^\]\n]*\])?: ([A-Za-z0-9_]{3,16}) joined the game[ \t\r]*$",
    re.MULTILINE,
)


@dataclass
class Status:
    online: int
    max: int
    players: dict = field(default_factory=dict)  # name -> uuid, from the sample the server returns

    @property
    def names(self) -> set:
        return set(self.players)


def joined_names(log_text: str) -> set[str]:
    return set(JOIN_LINE.findall(log_text))


def _varint(value: int) -> bytes:
    out = bytearray()
    value &= 0xFFFFFFFF
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


async def _read_varint(reader: asyncio.StreamReader) -> int:
    result = 0
    for shift in range(0, 35, 7):
        byte = (await reader.readexactly(1))[0]
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result
    raise ValueError("varint too long")


def _packet(payload: bytes) -> bytes:
    return _varint(len(payload)) + payload


async def ping(host: str, port: int, timeout: float = 5.0) -> Status | None:
    """
    Asks the server who is on. Returns None when it cannot be asked - callers must treat that as
    unknown, never as empty, or a network blip would read as everyone leaving.
    """
    writer = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)

        encoded = host.encode("utf-8")
        handshake = (_varint(0) + _varint(PROTOCOL_VERSION) + _varint(len(encoded)) + encoded
                     + struct.pack(">H", port) + _varint(1))
        writer.write(_packet(handshake) + _packet(_varint(0)))
        await writer.drain()

        async def read_response():
            await _read_varint(reader)  # packet length
            if await _read_varint(reader) != 0:
                raise ValueError("unexpected packet id")
            length = await _read_varint(reader)
            if length > 1_000_000:
                raise ValueError("status response too large")
            return json.loads((await reader.readexactly(length)).decode("utf-8"))

        data = await asyncio.wait_for(read_response(), timeout)
        players = data.get("players") or {}

        sample = {}
        for entry in players.get("sample") or []:
            name = str(entry.get("name", ""))
            uuid = str(entry.get("id", ""))
            # Players who turn off "Allow Server Listings" appear as "Anonymous Player" with a zero UUID.
            if MINECRAFT_NAME.match(name) and uuid.replace("-", "").strip("0"):
                sample[name] = uuid

        return Status(int(players.get("online", 0)), int(players.get("max", 0)), sample)
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError, TypeError, AttributeError):
        return None
    finally:
        if writer is not None:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()


class PanelError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Panel:
    """
    The Pterodactyl client API for one server.

    File reads go through the panel's editor endpoint, which refuses files over its edit size limit
    (4 MB by default). A very long session log can pass that, so anything read from latest.log is a
    supplement to the ping, not a replacement for it.
    """

    def __init__(self, url: str, key: str, server: str):
        self.base = f"{url.rstrip('/')}/api/client/servers/{server}"
        self.headers = {
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self.session: aiohttp.ClientSession | None = None

    async def _request(self, method: str, path: str, *, body=None, params=None, expect: str | None = "json"):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))

        async with self.session.request(method, self.base + path, headers=self.headers, json=body,
                                        params=params) as resp:
            if resp.status >= 400:
                text = (await resp.text())[:200]
                raise PanelError(f"{method} {path} -> {resp.status} {text}", resp.status)
            if expect == "json":
                return await resp.json()
            if expect == "text":
                return await resp.text()
            return None

    async def state(self) -> str:
        """One of: offline, starting, running, stopping."""
        data = await self._request("GET", "/resources")
        return data["attributes"]["current_state"]

    async def command(self, command: str) -> None:
        await self._request("POST", "/command", body={"command": command}, expect=None)

    async def power(self, signal: str) -> None:
        await self._request("POST", "/power", body={"signal": signal}, expect=None)

    async def read_file(self, path: str) -> str:
        return await self._request("GET", "/files/contents", params={"file": path}, expect="text")

    async def list_dir(self, path: str) -> set[str]:
        data = await self._request("GET", "/files/list", params={"directory": path})
        return {entry["attributes"]["name"] for entry in data.get("data", [])}


# Everything a panel call can fail with that should be survived rather than crash the watcher.
PANEL_ERRORS = (PanelError, aiohttp.ClientError, asyncio.TimeoutError, KeyError, TypeError, ValueError)
