"""
Unattended CivFabric playtest sessions.

Watches the Minecraft server, stops it once the session is over, and DMs everyone who played a link to
a feedback form, pre-filled with their name and CivFabric's telemetry session id so the answers join
onto civfabric-logs/*.csv.

Starting the server is not done here. A Pterodactyl schedule does it (backup, then power start), so a
session still happens if ZymBot is down. This module notices the server coming up and takes over from
there - including a server somebody started by hand, which is what /mc-admin hold is for.

When a session is over
----------------------
* Once more than MC_STOP_THRESHOLD players have been on together, the server stops after the count
  has stayed at or below the threshold for MC_STOP_GRACE_MINUTES. Chat gets a warning
  MC_STOP_WARN_MINUTES before, and anyone joining cancels it.
* Until then it only stops when empty, and not before MC_NO_SHOW_MINUTES after boot. One early player
  keeps it up rather than getting shut out for arriving first.
* MC_HARD_STOP stops it whatever else is true, warning at 10 minutes, 1 minute and 30 seconds. Either
  a clock time in MC_TIMEZONE ("02:00", the next one after the session starts) or a length ("6h",
  "90m", "6h30m") measured from the moment the bot picks the session up.
* A player count that cannot be read is unknown, never empty. Only the hard stop acts without one.

Stopping always uses the panel's stop signal, which types "stop" into the console. Never kill:
CivFabric's telemetry holds rows in memory and writes them on a clean shutdown.

When the server goes offline without ZymBot stopping it, it gets MC_CRASH_WAIT_MINUTES to come back,
because Wings restarts a crashed server by itself. Back within that window, it is the same session.

Who gets asked
--------------
mc_players.py, a hardcoded table of Minecraft name (or UUID) to Discord account. It is not committed,
because it names real people - copy mc_players.example.py and upload it beside .env. A UUID entry is
checked before the name table and survives a rename; names are matched case-insensitively.

The feedback form
-----------------
A Google Form, reached by a pre-filled link. MC_FORM_URL is the template: take it once from the form
editor (overflow menu > Get pre-filled link, fill the name and session fields, Get link), then swap
those two filled values for {name} and {session}. The bot substitutes and URL-encodes them per player,
so an answer arrives already saying who played and which session it was, and joins onto
civfabric-logs/*.csv without anybody typing an id.

The session value is normally one telemetry id, two joined by "+" when the server crashed and came
back, or "run-<time>" when the server has no telemetry.

The link also carries a form id, {form_id}: the session, a dot, and 12 base32 characters of HMAC over
the session and the player's Minecraft UUID, keyed by MC_FORM_SECRET. A response carrying a valid one
was issued by ZymBot to that player for that session, so somebody answering twice under another
player's name cannot produce the matching id. It is an HMAC rather than a stored random number so it
can be rechecked later without keeping a table of issued ids - form_id_matches does that check.

The session rides inside the id, so the sheet says which session a response belongs to without a
separate field for it.

Keep that field optional in the form. Somebody who never got a link should still be able to answer
with it blank - their answers are then unattributed rather than refused.

Answers live in the form's own responses sheet. ZymBot never sees them, so nothing here reads them
back - the only local record is which link went to whom, in runs.jsonl. A player can edit a pre-filled
field before submitting, which is worth knowing and not worth guarding against among friends.

Setup
-----
1. Minecraft server in Pterodactyl > Users: add a subuser for the bot with only Console (send
   commands), Stop, and File read + read content. Sign in as that user and create a client API key
   (Account > API Credentials). A key can do everything its account can, so do not use your own.
2. Minecraft server > Schedules: a schedule for the session start with two tasks - Create Backup,
   then Send Power Action: Start, with a time offset long enough for the backup to finish. Turn
   "Only When Server Is Online" OFF, or it never fires on a stopped server. Backups need the server's
   backup limit above 0 (admin area > Servers > Build Configuration). Schedules use the panel's
   timezone.
3. Fill in the .env keys below and restart ZymBot. None of this runs until the required ones are set.
4. Build the form, take its pre-filled link, and set MC_FORM_URL to it with {name} and {session} in
   place of the two filled-in values.
5. Fill in mc_players.py. Check it with /mc-admin players, and send yourself a link with
   /mc-admin test-feedback.

.env keys
---------
  MC_GUILD_ID               Discord server the /mc commands live in (required)
  PTERO_URL                 Panel address, e.g. https://panel.example.com (required)
  PTERO_API_KEY             Client API key from step 1 (required)
  PTERO_SERVER_ID           Short server id, from the panel URL of the Minecraft server (required)
  MC_HOST                   Address to ping, e.g. 195.201.199.249 (required)
  MC_PORT                   default 25565
  MC_ADDRESS                Address shown to players (default MC_HOST:MC_PORT)
  MC_STAFF_CHANNEL_ID       Alerts and session summaries (0 = console only)
  MC_ANNOUNCE_CHANNEL_ID    "Server is up / closed" posts for players (0 = off)
  MC_FORM_URL               Pre-filled link, with {form_id}, {session}, {name}, {discord} (empty = none sent)
  MC_FORM_SECRET            Keys the form id (default: one kept in mc_sessions_data/form_secret.txt)
  MC_FORM_MESSAGE           The DM that carries the link, {name} allowed (has a default)
  MC_STOP_THRESHOLD         default 1
  MC_STOP_GRACE_MINUTES     default 15
  MC_STOP_WARN_MINUTES      default 5
  MC_NO_SHOW_MINUTES        default 60
  MC_HARD_STOP              HH:MM clock time, or a length like 6h / 90m / 6h30m. Empty = no end time
  MC_TIMEZONE               default UTC, e.g. Europe/London
  MC_CRASH_WAIT_MINUTES     default 5
  MC_POLL_SECONDS           default 60
  MC_DATAPACK_NAME          Folder or zip expected in <world>/datapacks (default datapack, empty = no check)
  MC_DATAPACK_MISSING       stop or warn (default stop)
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import csv
import hashlib
import hmac
import importlib
import io
import json
import os
import re
import secrets
import time
import traceback
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from urllib.parse import quote

import discord
from discord import app_commands

import mc_status

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "mc_sessions_data"

HARD_STOP_WARNINGS = (600, 60, 30)   # seconds before MC_HARD_STOP
FINAL_WARNINGS = (60, 30)            # seconds before any stop, on top of MC_STOP_WARN_MINUTES
STOP_MESSAGE_LEAD = 3                # seconds between the goodbye and the server actually going
LOG_READ_EVERY = 10             # ticks between reads of latest.log during a session
BOOT_READ_TRIES = 5             # ticks to wait for this boot's telemetry row to appear
STUCK_STOPPING_SECONDS = 600    # still up this long after a stop, somebody should look
FORM_ID_CHARS = 12              # base32 characters of HMAC inside a form id
MESSAGE_LIMIT = 2000

DEFAULT_FORM_MESSAGE = ("Hi {name}, thanks for playing on the ZymLabs server today. Zym would appreciate "
                        "if you could fill up this feedback form!")


# --- config -----------------------------------------------------------------------------------------

@dataclass
class Config:
    guild_id: int
    panel_url: str
    panel_key: str
    server_id: str
    host: str
    port: int = 25565
    address: str = ""
    staff_channel: int = 0
    announce_channel: int = 0
    form_url: str = ""
    form_message: str = DEFAULT_FORM_MESSAGE
    threshold: int = 1
    grace: float = 15 * 60
    warn: float = 5 * 60
    no_show: float = 60 * 60
    hard_stop: str = ""
    tz: tzinfo = timezone.utc
    crash_wait: float = 5 * 60
    poll: float = 60
    datapack: str = "datapack"
    datapack_missing: str = "stop"

    @classmethod
    def from_env(cls) -> Config | None:
        required = ["MC_GUILD_ID", "PTERO_URL", "PTERO_API_KEY", "PTERO_SERVER_ID", "MC_HOST"]
        missing = [key for key in required if not os.getenv(key, "").strip()]
        if missing:
            print(f"Minecraft sessions: off ({', '.join(missing)} not set)")
            return None

        # A bad value keeps its default and says so, rather than keeping the bot from starting.
        def number(key, default):
            raw = os.getenv(key, "").strip()
            if not raw:
                return default
            try:
                return int(raw)
            except ValueError:
                print(f"Minecraft sessions: {key}={raw!r} is not a whole number, using {default}")
                return default

        guild_id = number("MC_GUILD_ID", 0)
        if not guild_id:
            print("Minecraft sessions: off (MC_GUILD_ID is not a server id)")
            return None

        host = os.getenv("MC_HOST", "").strip()
        port = number("MC_PORT", 25565)

        tz_name = os.getenv("MC_TIMEZONE", "").strip() or "UTC"
        if tz_name.upper() == "UTC":
            # Named zones need the system tz database, which a slim container may not carry. UTC does not.
            tz = timezone.utc
        else:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(tz_name)
            except Exception as exc:
                print(f"Minecraft sessions: cannot use MC_TIMEZONE {tz_name!r} ({exc}) - falling back to UTC. "
                      "A container without the tz database needs the tzdata package.")
                tz = timezone.utc

        hard_stop = os.getenv("MC_HARD_STOP", "").strip()
        if hard_stop and parse_deadline(hard_stop) is None:
            print(f"Minecraft sessions: MC_HARD_STOP={hard_stop!r} is neither HH:MM nor a length like 6h, "
                  "so there is no end time")
            hard_stop = ""

        form_url = os.getenv("MC_FORM_URL", "").strip()
        if not form_url:
            print("Minecraft sessions: MC_FORM_URL is not set, so no feedback links will be sent")
        elif "{session}" not in form_url and "{form_id}" not in form_url:
            print("Minecraft sessions: MC_FORM_URL has neither {session} nor {form_id}, so answers will not "
                  "say which session they are about")

        missing_action = os.getenv("MC_DATAPACK_MISSING", "stop").strip().lower()
        if missing_action not in ("stop", "warn"):
            print(f"Minecraft sessions: MC_DATAPACK_MISSING={missing_action!r} is not stop or warn, using stop")
            missing_action = "stop"

        return cls(
            guild_id=guild_id,
            panel_url=os.getenv("PTERO_URL", "").strip(),
            panel_key=os.getenv("PTERO_API_KEY", "").strip(),
            server_id=os.getenv("PTERO_SERVER_ID", "").strip(),
            host=host,
            port=port,
            address=os.getenv("MC_ADDRESS", "").strip() or f"{host}:{port}",
            staff_channel=number("MC_STAFF_CHANNEL_ID", 0),
            announce_channel=number("MC_ANNOUNCE_CHANNEL_ID", 0),
            form_url=form_url,
            form_message=os.getenv("MC_FORM_MESSAGE", "").strip() or DEFAULT_FORM_MESSAGE,
            threshold=max(0, number("MC_STOP_THRESHOLD", 1)),
            grace=max(1, number("MC_STOP_GRACE_MINUTES", 15)) * 60,
            warn=max(0, number("MC_STOP_WARN_MINUTES", 5)) * 60,
            no_show=max(0, number("MC_NO_SHOW_MINUTES", 60)) * 60,
            hard_stop=hard_stop,
            tz=tz,
            crash_wait=max(1, number("MC_CRASH_WAIT_MINUTES", 5)) * 60,
            poll=max(15, number("MC_POLL_SECONDS", 60)),
            datapack=os.getenv("MC_DATAPACK_NAME", "datapack").strip(),
            datapack_missing=missing_action,
        )


def parse_clock(text: str):
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not match:
        return None
    hour, minute = int(match[1]), int(match[2])
    return (hour, minute) if hour < 24 and minute < 60 else None


def parse_deadline(text: str):
    """
    ("clock", (hour, minute)) for a time of day, or ("after", seconds) for a length.

    One setting takes both because they answer the same question in different words: "be off by 2am"
    and "run for six hours" are each the natural phrasing for some sessions.
    """
    text = text.strip().lower()
    clock = parse_clock(text)
    if clock:
        return "clock", clock
    span = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?", text)
    if not text or not span or not (span[1] or span[2]):
        return None
    seconds = int(span[1] or 0) * 3600 + int(span[2] or 0) * 60
    return ("after", seconds) if seconds > 0 else None


def next_clock_time(after: float, clock: str, tz: tzinfo) -> float:
    """The first HH:MM strictly after a moment, so a 02:00 end on a 13:00 start means tomorrow."""
    hour, minute = parse_clock(clock)
    local = datetime.fromtimestamp(after, tz)
    target = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    return target.timestamp()


def minutes_text(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes > 1:
        return f"{minutes} minutes"
    return "1 minute" if minutes == 1 else "under a minute"


def countdown_text(seconds: float) -> str:
    """Rounded the way somebody reading chat would say it, down to ten-second steps."""
    if seconds >= 90:
        return f"{round(seconds / 60)} minutes"
    if seconds >= 45:
        return "1 minute"
    return f"{max(5, int(round(seconds / 10)) * 10)} seconds"


def warn_points(cfg) -> list:
    """When to warn before a stop: the configured one, then the last-minute reminders."""
    return sorted({point for point in (cfg.warn,) + FINAL_WARNINGS if 0 < point < cfg.grace}, reverse=True)


def span_text(seconds: float) -> str:
    hours, minutes = divmod(int(seconds // 60), 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


# --- the stop rule ----------------------------------------------------------------------------------

@dataclass
class Run:
    """One session, from the server coming up to the feedback going out. Saved every tick, so a
    ZymBot restart picks it back up."""

    started: float
    hard_stop_at: float | None = None
    peak: int = 0
    low_since: float | None = None
    low_warned_at: list = field(default_factory=list)   # warning points already said
    empty_since: float | None = None
    hard_warned: list = field(default_factory=list)
    roster: dict = field(default_factory=dict)      # Minecraft name -> uuid, "" when only the log saw them
    sessions: list = field(default_factory=list)      # CivFabric telemetry session ids, one per boot
    telemetry: dict = field(default_factory=dict)     # the latest sessions.csv row
    booted: bool = False                              # this boot's datapack check is done
    boot_tries: int = 0
    boot_session_found: bool = False
    offline_since: float | None = None
    restarts: int = 0
    hold: bool = False
    send_feedback: bool = True
    pending_stop: str | None = None                   # decided to stop, panel has not accepted yet
    stop_failures: int = 0
    stopping: str | None = None                       # panel accepted the stop
    stop_requested_at: float | None = None
    stuck_alerted: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> Run:
        known = {f.name for f in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in known})

    def add_players(self, players) -> None:
        """A name -> uuid mapping from a ping, or bare names from the log."""
        if not isinstance(players, dict):
            players = {name: "" for name in players}
        for name, uuid in players.items():
            # A uuid, once seen, is never replaced by the blank one the log gives.
            if uuid or name not in self.roster:
                self.roster[name] = uuid or self.roster.get(name, "")

    def names(self) -> list:
        return sorted(self.roster, key=str.lower)


@dataclass
class Decision:
    kind: str           # "say" or "stop"
    message: str        # for players, in chat
    reason: str = ""    # for the staff summary


def decide(run: Run, cfg: Config, now: float, online: int | None) -> Decision | None:
    """What to do this tick. Touches nothing but the run's own timers, so it tests without a server."""
    if run.hold or run.stopping or run.pending_stop:
        return None

    if run.hard_stop_at is not None:
        left = run.hard_stop_at - now
        if left <= 0:
            return Decision("stop", "That's the end of today's session - the server is stopping now. Thanks for playing!",
                            "reached the end time")
        due = [point for point in HARD_STOP_WARNINGS if left <= point and point not in run.hard_warned]
        if due:
            run.hard_warned.extend(due)
            return Decision("say", f"The server closes for the day in {countdown_text(left)}.")

    if online is None:
        return None

    run.peak = max(run.peak, online)

    if run.peak > cfg.threshold:
        run.empty_since = None

        if online > cfg.threshold:
            warned = bool(run.low_warned_at)
            run.low_since, run.low_warned_at = None, []
            return Decision("say", "Players are back, so the server is staying up.") if warned else None

        if run.low_since is None:
            run.low_since = now
        left = run.low_since + cfg.grace - now

        if left <= 0:
            return Decision("stop", "The session is over - the server is stopping now. Thanks for playing!",
                            f"{online} online for {minutes_text(cfg.grace)} (threshold {cfg.threshold})")
        due = [point for point in warn_points(cfg) if left <= point and point not in run.low_warned_at]
        if due:
            # Every point still owed is marked, so a slow tick that skips one does not say it late.
            run.low_warned_at.extend(due)
            who = "Everyone has" if online == 0 else "Most players have"
            return Decision("say", f"{who} left, so the server stops in {countdown_text(left)}. Anyone joining keeps it up.")
        return None

    # Never busier than the threshold. One player keeps it up; an empty server closes once the no-show
    # window has passed and it has been empty for the grace period.
    if online > 0:
        run.empty_since = None
        return None
    if run.empty_since is None:
        run.empty_since = now
    if now >= max(run.started + cfg.no_show, run.empty_since + cfg.grace):
        return Decision("stop", "Nobody is on, so the server is stopping.",
                        "nobody joined" if run.peak == 0 else "empty, and never busier than the threshold")
    return None


# --- storage ----------------------------------------------------------------------------------------

def normalise_uuid(value) -> str | None:
    text = str(value).replace("-", "").strip().lower()
    return text if re.fullmatch(r"[0-9a-f]{32}", text) else None


def load_players(reload: bool = False) -> tuple | None:
    """
    The hardcoded table from mc_players.py, or None when the file cannot be read at all.

    A missing file is not fatal: the watcher still runs, and the session summary names everyone who
    played, so an empty table reads as "not in mc_players.py" against real names rather than as
    silence. One bad row is skipped rather than costing the rest of the table.
    """
    try:
        import mc_players
        if reload:
            importlib.reload(mc_players)
    except Exception as exc:
        print(f"Minecraft sessions: no usable mc_players.py ({exc}) - nobody will be asked for feedback")
        return None

    def discord_id_of(value):
        """0 is the placeholder a half-filled table carries, and is not an id."""
        text = str(value).strip()
        return int(text) if text.isdigit() and int(text) > 0 else None

    by_name, by_uuid = {}, {}
    for name, entry in dict(getattr(mc_players, "PLAYERS", {})).items():
        # Either "Name": id, or "Name": {"discord": id, "uuid": "..."} so a player is one line to edit.
        details = entry if isinstance(entry, dict) else {"discord": entry}
        discord_id = discord_id_of(details.get("discord"))
        if not mc_status.MINECRAFT_NAME.match(str(name)) or discord_id is None:
            print(f"Minecraft sessions: skipping mc_players entry {name!r} - it still needs a Discord id")
            continue
        by_name[str(name).lower()] = {"name": str(name), "discord": discord_id}
        uuid = normalise_uuid(details.get("uuid")) if details.get("uuid") else None
        if uuid:
            by_uuid[uuid] = discord_id

    for uuid, value in dict(getattr(mc_players, "UUIDS", {})).items():
        key, discord_id = normalise_uuid(uuid), discord_id_of(value)
        if key is None or discord_id is None:
            print(f"Minecraft sessions: skipping mc_players UUID entry {uuid!r} -> {value!r}")
            continue
        by_uuid[key] = discord_id

    return by_name, by_uuid


class Store:
    """Everything that has to survive a restart: the open run and the answers."""

    def __init__(self, tz: tzinfo, directory=None):
        self.tz = tz
        self.directory = Path(directory or DATA_DIR)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.state_file = self.directory / "state.json"
        self.history_file = self.directory / "runs.jsonl"
        self.secret_file = self.directory / "form_secret.txt"
        self.secret = self._form_secret()
        self.players, self.uuids = load_players() or ({}, {})

    def _read_json(self, path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default
        except (OSError, ValueError) as exc:
            # Moved aside rather than overwritten by the next save, so a bad hand edit loses nothing.
            aside = path.with_name(f"{path.name}.broken-{int(time.time())}")
            with contextlib.suppress(OSError):
                path.replace(aside)
            print(f"Minecraft sessions: could not read {path.name} ({exc}) - moved it to {aside.name} and started empty")
            return default

    def _write_json(self, path: Path, data) -> bool:
        try:
            temp = path.with_name(path.name + ".tmp")
            temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(temp, path)
            return True
        except OSError as exc:
            print(f"Minecraft sessions: could not write {path.name} ({exc})")
            return False

    def _form_secret(self) -> bytes:
        """
        Keys the form id. MC_FORM_SECRET when set, otherwise one generated once and kept beside the
        rest of the state. Losing it breaks nothing in the moment - it only makes ids issued before
        it unverifiable afterwards, which is why the env var exists for anybody who would rather hold
        it themselves.
        """
        from_env = os.getenv("MC_FORM_SECRET", "").strip()
        if from_env:
            return from_env.encode("utf-8")
        try:
            if self.secret_file.exists():
                kept = self.secret_file.read_text(encoding="utf-8").strip()
                if kept:
                    return kept.encode("utf-8")
            fresh = secrets.token_hex(32)
            self.secret_file.write_text(fresh, encoding="utf-8")
            return fresh.encode("utf-8")
        except OSError as exc:
            print(f"Minecraft sessions: could not keep a form secret ({exc}) - form ids will change on restart")
            return secrets.token_hex(32).encode("utf-8")

    def load_state(self):
        data = self._read_json(self.state_file, {})
        try:
            run = Run.from_dict(data["run"]) if data.get("run") else None
        except TypeError as exc:
            print(f"Minecraft sessions: saved session unreadable ({exc}), starting fresh")
            run = None
        return run, data.get("last_session")

    def save_state(self, run: Run | None, last_session: str | None) -> None:
        self._write_json(self.state_file, {"run": asdict(run) if run else None, "last_session": last_session})

    def owner(self, name: str, uuid: str | None = None) -> int | None:
        """A UUID entry wins, so somebody who renamed themselves still gets their form."""
        key = normalise_uuid(uuid) if uuid else None
        if key and key in self.uuids:
            return self.uuids[key]
        entry = self.players.get(name.lower())
        return entry["discord"] if entry else None

    def names_for(self, discord_id: int) -> list:
        return sorted((e["name"] for e in self.players.values() if e["discord"] == discord_id), key=str.lower)

    def reload_players(self) -> bool:
        """A typo in the file mid-session keeps the table already in memory rather than emptying it."""
        table = load_players(reload=True)
        if table is None:
            return False
        self.players, self.uuids = table
        return True

    def history(self) -> list:
        """Past runs, oldest first. One line per session, so it is read whole without ceremony."""
        entries = []
        try:
            lines = self.history_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return entries
        for line in lines:
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue  # a half-written line from a kill costs that row, not the file
        return entries

    def append_history(self, entry: dict) -> None:
        try:
            with self.history_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")
        except OSError as exc:
            print(f"Minecraft sessions: could not write runs.jsonl ({exc})")


# --- the feedback form ------------------------------------------------------------------------------

def session_key(run: Run, tz: tzinfo) -> str:
    if run.sessions:
        return "+".join(run.sessions[-2:])
    return "run-" + datetime.fromtimestamp(run.started, tz).strftime("%Y%m%d-%H%M%S")


def form_id(secret: bytes, session: str, subject: str) -> str:
    """
    The anti-impersonation id for one player in one session: the session, a dot, and 12 base32
    characters of HMAC.

    The session travels inside the id deliberately. Nothing else in the link says which session a
    response belongs to, and a checker without it would have to try every session it knew.

    Twelve base32 characters is 60 bits. Nobody types this - ZymBot fills it in - so it is sized for
    guessing resistance rather than for reading aloud.
    """
    digest = hmac.new(secret, f"{session}:{subject}".encode("utf-8"), hashlib.sha256).digest()
    return f"{session}.{base64.b32encode(digest).decode('ascii').rstrip('=')[:FORM_ID_CHARS]}"


def form_id_matches(secret: bytes, value: str, subject: str) -> bool:
    """
    Whether an id from the response sheet is one ZymBot issued to this player.

    compare_digest rather than ==, which is habit rather than need: the attacker here is a friend with
    a spreadsheet, not a timing oracle.
    """
    value = value.strip()
    session = value.rpartition(".")[0]
    return bool(session) and hmac.compare_digest(form_id(secret, session, subject), value)


def form_link(template: str, session: str, name: str, discord: str = "", form: str = "") -> str:
    """
    One player's pre-filled form link.

    Substituted by hand rather than through str.format, so a template carrying any other brace cannot
    raise on a Saturday evening, and URL-encoded so a "+" in a two-boot session id survives the trip.

    {discord} is the account handle rather than the display name: a display name changes whenever its
    owner feels like it, and the handle is what the Discord id in mc_players.py actually belongs to.
    """
    return (template.replace("{form_id}", quote(form, safe=""))
                    .replace("{session}", quote(session, safe=""))
                    .replace("{name}", quote(name, safe=""))
                    .replace("{discord}", quote(discord, safe="")))


def verify_form_id(store: Store, value: str) -> tuple:
    """
    Who a form id was issued to, as (label, session).

    The id names its own session, so the search is only over the players who could have been issued
    one for it: whoever the run history says played, plus everybody in mc_players. label is None when
    nothing matches, and session is "" when the value is not shaped like an id at all.
    """
    value = value.strip()
    session = value.rpartition(".")[0]
    if not session:
        return None, ""

    candidates = {}  # subject -> what to call them
    for entry in store.history():
        if session not in str(entry.get("session_key", "")):
            continue
        for name, uuid in (entry.get("roster") or {}).items():
            key = normalise_uuid(uuid) if uuid else None
            if key:
                candidates.setdefault(key, name)
            candidates.setdefault(name.lower(), name)

    for uuid, discord_id in store.uuids.items():
        candidates.setdefault(uuid, f"<@{discord_id}>")
    for lowered, entry in store.players.items():
        candidates.setdefault(lowered, entry["name"])
    candidates.setdefault("tester", "a /mc-admin test-feedback link")

    for subject, label in candidates.items():
        if form_id_matches(store.secret, value, subject):
            return label, session
    return None, session


async def send_link(user, cfg: Config, session: str, name: str, form: str = "") -> str:
    """
    DMs one player their link.

    A link button needs no custom_id and no registration, so unlike the answer buttons this replaced,
    nothing has to survive a restart: the link is whole in the message.
    """
    link = form_link(cfg.form_url, session, name, getattr(user, "name", "") or "", form)
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Open the feedback form", style=discord.ButtonStyle.link, url=link))
    await user.send(cfg.form_message.replace("{name}", name), view=view)
    return link



# --- the watcher ------------------------------------------------------------------------------------

def parse_properties(text: str) -> dict:
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "!")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


class Watcher:
    def __init__(self, client, cfg: Config, panel, store: Store):
        self.client, self.cfg, self.panel, self.store = client, cfg, panel, store
        self.run, self.last_session = store.load_state()
        self.ticks = 0
        self.task = None
        self._problems: dict = {}

    def save(self) -> None:
        self.store.save_state(self.run, self.last_session)

    def problem(self, kind: str, text: str) -> None:
        # Printed once per distinct problem, so a panel outage does not fill the console every minute.
        if self._problems.get(kind) != text:
            self._problems[kind] = text
            print(f"Minecraft sessions: {text}")

    def clear(self, kind: str) -> None:
        self._problems.pop(kind, None)

    async def loop(self) -> None:
        await self.client.wait_until_ready()
        print(f"Minecraft sessions: watching {self.cfg.address}")
        while not self.client.is_closed():
            try:
                await self.tick(time.time())
            except Exception:
                traceback.print_exc()
            await asyncio.sleep(self.next_delay())

    def next_delay(self) -> float:
        """
        How long to wait before the next tick.

        A minute between polls would land a "30 seconds" warning anywhere in the half minute after it
        was due, so as a deadline approaches the loop tightens up to meet it. Never below five seconds,
        which is far more often than anything here needs.
        """
        run = self.run
        if run is None or run.hold or run.stopping or run.pending_stop:
            return self.cfg.poll

        deadlines = []
        if run.hard_stop_at is not None:
            deadlines += [run.hard_stop_at] + [run.hard_stop_at - point for point in HARD_STOP_WARNINGS]
        if run.low_since is not None and run.peak > self.cfg.threshold:
            stop_at = run.low_since + self.cfg.grace
            deadlines += [stop_at] + [stop_at - point for point in warn_points(self.cfg)]

        now = time.time()
        ahead = [deadline - now for deadline in deadlines if deadline > now]
        return max(5.0, min([self.cfg.poll] + ahead))

    async def tick(self, now: float) -> None:
        self.ticks += 1
        try:
            state = await self.panel.state()
        except mc_status.PANEL_ERRORS as exc:
            self.problem("panel", f"panel unreachable - {exc}")
            return
        self.clear("panel")

        up = state in ("starting", "running")
        run = self.run

        if run is None:
            if not up:
                return
            run = self.run = self.open_run(now)
            self.save()
            await self.post(self.cfg.announce_channel, f"The ZymLabs server is starting up - `{self.cfg.address}`")

        if state == "stopping":
            return

        if not up:
            run.booted, run.boot_tries, run.boot_session_found = False, 0, False
            if run.stopping or run.pending_stop:
                await self.close_run(run, now, crashed=False)
                return
            if run.offline_since is None:
                run.offline_since = now
                self.save()
            if now - run.offline_since >= self.cfg.crash_wait:
                await self.close_run(run, now, crashed=True)
            return

        if run.offline_since is not None:
            run.offline_since = None
            run.restarts += 1
            await self.staff("The server went down without ZymBot stopping it, and came back up by itself. "
                             "Treating it as the same session - worth checking the console for a crash.")

        if state != "running":
            self.save()
            return

        await self.boot_checks(run)

        if run.pending_stop and not run.stopping:
            await self.stop(run, now, run.pending_stop, None)
        if run.stopping:
            if now - (run.stop_requested_at or now) >= STUCK_STOPPING_SECONDS and not run.stuck_alerted:
                run.stuck_alerted = True
                await self.staff(f"The server is still up {STUCK_STOPPING_SECONDS // 60} minutes after ZymBot asked it to stop. "
                                 "Not killing it, since that loses unsaved telemetry - check the console.")
            self.save()
            return

        status = await mc_status.ping(self.cfg.host, self.cfg.port)
        if status is None:
            self.problem("ping", f"no answer from {self.cfg.host}:{self.cfg.port}")
        else:
            self.clear("ping")
            run.add_players(status.players)

        # The ping only lists a sample of names, and latest.log rolls over at midnight, so read it as we go.
        if self.ticks % LOG_READ_EVERY == 0:
            await self.read_log(run)

        decision = decide(run, self.cfg, now, None if status is None else status.online)
        if decision is not None:
            if decision.kind == "stop":
                await self.stop(run, now, decision.reason, decision.message)
            else:
                await self.say(decision.message)
        self.save()

    def open_run(self, now: float) -> Run:
        hard = None
        if self.cfg.hard_stop:
            kind, value = parse_deadline(self.cfg.hard_stop)
            hard = now + value if kind == "after" else next_clock_time(now, self.cfg.hard_stop, self.cfg.tz)
        return Run(started=now, hard_stop_at=hard)

    async def boot_checks(self, run: Run) -> None:
        if not run.booted:
            run.booted = True
            await self.check_datapack(run)

        if run.boot_session_found or run.boot_tries >= BOOT_READ_TRIES:
            return
        run.boot_tries += 1

        row = await self.read_telemetry()
        session = (row or {}).get("session")
        # The last row can still be the previous boot's for a moment after "running", so only a new id counts.
        if session and session != self.last_session and session not in run.sessions:
            run.sessions.append(session)
            run.telemetry = row
            self.last_session = session
            run.boot_session_found = True
        elif run.boot_tries >= BOOT_READ_TRIES:
            self.problem("telemetry", "no new CivFabric telemetry session after boot - feedback will use ZymBot's own run id")

    async def read_telemetry(self) -> dict | None:
        try:
            text = await self.panel.read_file("/civfabric-logs/sessions.csv")
        except mc_status.PANEL_ERRORS:
            return None
        rows = list(csv.DictReader(io.StringIO(text)))
        return rows[-1] if rows else None

    async def check_datapack(self, run: Run) -> None:
        name = self.cfg.datapack
        if not name:
            return

        try:
            level = parse_properties(await self.panel.read_file("/server.properties")).get("level-name") or "world"
            try:
                present = await self.panel.list_dir(f"/{level}/datapacks")
            except mc_status.PanelError as exc:
                if exc.status != 404:
                    raise
                present = set()  # no datapacks folder at all is a definite answer
        except mc_status.PANEL_ERRORS as exc:
            # Unknown is not the same as missing, so this only warns.
            await self.staff(f"Couldn't check for the datapack ({exc}). Leaving the server up - check `{name}` "
                             "is in the world's datapacks folder by hand.")
            return

        if name in present or f"{name}.zip" in present:
            return

        where = f"`{level}/datapacks/{name}`"
        found = ", ".join(sorted(present)) or "nothing"
        if self.cfg.datapack_missing == "stop":
            # Portals built in an 8:1 Nether stay in the wrong place after the datapack is fixed, so
            # this is worth stopping for before anyone plays, rather than warning about afterwards.
            run.send_feedback = False
            run.pending_stop = "datapack missing"
            await self.staff(f"**Datapack missing:** {where} isn't there (found: {found}). Without it the world gets "
                             "vanilla's 8:1 Nether and none of the moon tuning, so the server is being stopped before "
                             "anyone plays on it.")
            await self.say("This server is missing a required datapack and is shutting down. An admin has been told - sorry!")
        else:
            await self.staff(f"**Datapack missing:** {where} isn't there (found: {found}). Left running because "
                             "MC_DATAPACK_MISSING=warn.")

    async def read_log(self, run: Run) -> None:
        try:
            text = await self.panel.read_file("/logs/latest.log")
        except mc_status.PANEL_ERRORS as exc:
            self.problem("log", f"couldn't read latest.log ({exc}) - the player list relies on pings alone")
            return
        self.clear("log")
        run.add_players(mc_status.joined_names(text))

    async def say(self, message: str) -> None:
        try:
            await self.panel.command(f"say {message}")
        except mc_status.PANEL_ERRORS as exc:
            self.problem("say", f"couldn't send a chat message ({exc})")

    async def stop(self, run: Run, now: float, reason: str, message: str | None) -> None:
        if message and run.stop_failures == 0:
            await self.say(message)
            # Chat is only worth saying if it arrives before the shutdown wipes it off the screen.
            await asyncio.sleep(STOP_MESSAGE_LEAD)
        run.pending_stop = reason
        try:
            await self.panel.power("stop")
        except mc_status.PANEL_ERRORS as exc:
            run.stop_failures += 1
            self.problem("stop", f"the panel refused the stop ({exc})")
            if run.stop_failures == 3:
                await self.staff(f"ZymBot has tried to stop the server three times and the panel refused: {exc}")
            self.save()
            return
        self.clear("stop")
        run.stopping, run.stop_requested_at = reason, now
        self.save()

    async def close_run(self, run: Run, now: float, crashed: bool) -> None:
        # Cleared and saved first, so a failure anywhere below cannot close the same session twice.
        self.run = None
        self.save()

        # latest.log is left alone until the next boot, so it still holds the session.
        await self.read_log(run)
        session = session_key(run, self.cfg.tz)

        if crashed:
            reason = "the server went offline without ZymBot stopping it (a crash, or stopped from the panel)"
        else:
            reason = f"stopped - {run.stopping or run.pending_stop}"

        lines = [f"**Session over:** {reason}",
                 f"Ran {span_text(now - run.started)}, peak {run.peak} online"
                 + (f", came back from {run.restarts} crash(es)" if run.restarts else "")]
        if run.telemetry:
            t = run.telemetry
            # In sessions.csv, "classes" is the count and "active" names them.
            lines.append(f"CivFabric {t.get('mod_version', '?')}, {t.get('slots', '?')} slots, "
                         f"{t.get('classes', '?')} classes: {t.get('active', '?')}")
        lines.append(f"Feedback tagged `{session}`")
        lines.append(f"Players: {', '.join(run.names()) or 'nobody'}")

        if not run.send_feedback:
            lines.append("No feedback asked for this session.")
        elif not self.cfg.form_url:
            lines.append("No feedback links sent: MC_FORM_URL is not set.")
        elif run.roster:
            sent, unknown, failed = await self.send_feedback(session, run.roster)
            lines.append(f"Feedback sent to: {', '.join(sent) or 'nobody'}")
            if unknown:
                lines.append(f"Not in mc_players.py, so not asked: {', '.join(unknown)}")
            if failed:
                lines.append(f"Couldn't DM (DMs closed?): {', '.join(failed)}")

        await self.staff("\n".join(lines))
        await self.post(self.cfg.announce_channel, "The ZymLabs server is closed for now. Thanks for playing!")

        entry = asdict(run)
        entry.update(ended=now, crashed=crashed, session_key=session)
        self.store.append_history(entry)

    def subject_for(self, name: str, roster: dict) -> str:
        """
        What a form id is tied to: the player's UUID when one was seen, their name otherwise.

        A UUID is better because it survives a rename, but a ping only samples some players and the
        log carries no UUIDs at all - so mc_players is asked next, and the name is the last resort.
        """
        seen = normalise_uuid(roster.get(name)) if roster.get(name) else None
        if seen:
            return seen
        owner = self.store.owner(name)
        if owner is not None:
            for uuid, discord_id in self.store.uuids.items():
                if discord_id == owner:
                    return uuid
        return name.lower()

    async def send_feedback(self, session: str, roster: dict) -> tuple:
        sent, unknown, failed = [], [], []
        by_user: dict = {}
        for name in sorted(roster, key=str.lower):
            owner = self.store.owner(name, roster.get(name))
            if owner is None:
                unknown.append(name)
            else:
                by_user.setdefault(owner, []).append(name)

        # One link per Discord account, even if they played on two Minecraft names.
        for discord_id, mc_names in by_user.items():
            label = "/".join(mc_names)
            try:
                user = self.client.get_user(discord_id) or await self.client.fetch_user(discord_id)
                token = form_id(self.store.secret, session, self.subject_for(mc_names[0], roster))
                await send_link(user, self.cfg, session, mc_names[0], token)
                sent.append(label)
            except discord.HTTPException as exc:
                print(f"Minecraft sessions: couldn't DM {label} ({exc})")
                failed.append(label)
        return sent, unknown, failed

    async def post(self, channel_id: int, text: str) -> None:
        if not channel_id:
            return
        try:
            channel = self.client.get_channel(channel_id) or await self.client.fetch_channel(channel_id)
            await channel.send(text[:MESSAGE_LIMIT], allowed_mentions=discord.AllowedMentions.none())
        except (discord.HTTPException, AttributeError) as exc:
            print(f"Minecraft sessions: couldn't post to channel {channel_id} ({exc})")

    async def staff(self, text: str) -> None:
        print(f"Minecraft sessions: {text}")
        await self.post(self.cfg.staff_channel, text)

    async def describe(self) -> str:
        try:
            state = await self.panel.state()
        except mc_status.PANEL_ERRORS:
            state = "unknown"
        lines = [f"Server: **{state}** - `{self.cfg.address}`"]

        if state == "running":
            status = await mc_status.ping(self.cfg.host, self.cfg.port)
            if status is None:
                lines.append("Not answering pings right now.")
            else:
                names = ", ".join(sorted(status.names, key=str.lower))
                lines.append(f"Online: **{status.online}/{status.max}**" + (f" - {names}" if names else ""))

        run = self.run
        if run is not None:
            # Discord timestamps show in each reader's own timezone.
            if run.hold:
                lines.append("On hold - it won't stop by itself.")
            elif run.stopping or run.pending_stop:
                lines.append("Stopping now.")
            else:
                if run.low_since is not None:
                    lines.append(f"Stops <t:{int(run.low_since + self.cfg.grace)}:t> unless someone joins.")
                if run.hard_stop_at is not None:
                    lines.append(f"Closes for the day <t:{int(run.hard_stop_at)}:t>.")
        return "\n".join(lines)


# --- commands ---------------------------------------------------------------------------------------

def register_commands(tree: app_commands.CommandTree, watcher: Watcher) -> None:
    guild = discord.Object(id=watcher.cfg.guild_id)
    store = watcher.store

    mc = app_commands.Group(name="mc", description="The CivFabric Minecraft server")

    @mc.command(name="status", description="Is the server up, and who's on?")
    async def mc_status_command(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(await watcher.describe(), ephemeral=True)

    admin = app_commands.Group(name="mc-admin", description="Control unattended CivFabric sessions",
                               default_permissions=discord.Permissions(manage_guild=True))

    async def refused(interaction: discord.Interaction) -> bool:
        # default_permissions can be loosened per server in Discord's settings, so check again here.
        if interaction.permissions.manage_guild:
            return False
        await interaction.response.send_message("You need Manage Server to do that.", ephemeral=True)
        return True

    async def no_session(interaction: discord.Interaction) -> bool:
        if watcher.run is not None:
            return False
        await interaction.response.send_message("No session is being watched right now.", ephemeral=True)
        return True

    @admin.command(name="hold", description="Keep this session up - ZymBot won't stop the server until you resume")
    @app_commands.describe(send_feedback="Still DM players the feedback form when this session ends")
    async def admin_hold(interaction: discord.Interaction, send_feedback: bool = True):
        if await refused(interaction) or await no_session(interaction):
            return
        run = watcher.run
        run.hold, run.send_feedback = True, send_feedback
        run.low_since, run.low_warned_at, run.empty_since = None, [], None
        watcher.save()
        await interaction.response.send_message(
            "On hold - the server stays up until `/mc-admin resume` or you stop it."
            + ("" if send_feedback else " No feedback will be asked for."), ephemeral=True)

    @admin.command(name="resume", description="Let ZymBot stop the server by itself again")
    async def admin_resume(interaction: discord.Interaction):
        if await refused(interaction) or await no_session(interaction):
            return
        run = watcher.run
        run.hold = False
        run.low_since, run.low_warned_at, run.empty_since = None, [], None
        watcher.save()
        late = run.hard_stop_at is not None and run.hard_stop_at <= time.time()
        await interaction.response.send_message(
            "Resumed." + (" The end time has already passed, so it stops at the next check." if late else ""), ephemeral=True)

    @admin.command(name="stop", description="Stop the server cleanly now, and send the feedback form")
    async def admin_stop(interaction: discord.Interaction):
        if await refused(interaction) or await no_session(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        run = watcher.run
        await watcher.stop(run, time.time(), f"stopped by {interaction.user}", "An admin is stopping the server now. Thanks for playing!")
        await interaction.followup.send("Stop sent." if run.stopping else "The panel refused the stop - ZymBot will keep trying.", ephemeral=True)

    @admin.command(name="players", description="Show the Minecraft to Discord table, re-reading mc_players.py")
    async def admin_players(interaction: discord.Interaction):
        if await refused(interaction):
            return
        # Re-read rather than use what was loaded at boot, so adding somebody needs no restart.
        reloaded = store.reload_players()
        lines = [f"**mc_players.py: {len(store.players)} names, {len(store.uuids)} UUIDs**"]
        if not reloaded:
            lines.append("(could not re-read the file just now - this is what was loaded before)")
        for entry in sorted(store.players.values(), key=lambda e: e["name"].lower()):
            lines.append(f"`{entry['name']}` -> <@{entry['discord']}>")
        for uuid, discord_id in sorted(store.uuids.items()):
            lines.append(f"`{uuid}` -> <@{discord_id}>")
        await interaction.response.send_message("\n".join(lines)[:MESSAGE_LIMIT], ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())

    @admin.command(name="verify", description="Check a form id from the response sheet: who it was issued to")
    @app_commands.describe(form_id="The value pasted out of the sheet")
    async def admin_verify(interaction: discord.Interaction, form_id: str):
        if await refused(interaction):
            return
        label, session = verify_form_id(store, form_id)
        if not session:
            message = "That isn't shaped like a form id. They read like `20260919-130000.K7QF3M2ZT4XB`."
        elif label is None:
            message = (f"**No match** for session `{session}`. Either the field was edited or typed by hand, "
                       "the id predates the current MC_FORM_SECRET, or it was issued by another instance.")
        else:
            message = f"Issued to **{label}** for session `{session}`. The id checks out."
        await interaction.response.send_message(message, ephemeral=True,
                                                allowed_mentions=discord.AllowedMentions.none())

    @admin.command(name="test-feedback", description="DM yourself a feedback link, filled in with the session 'test'")
    async def admin_test_feedback(interaction: discord.Interaction):
        if await refused(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        if not watcher.cfg.form_url:
            await interaction.followup.send("MC_FORM_URL is not set, so there is no form to send.", ephemeral=True)
            return
        names = store.names_for(interaction.user.id)
        try:
            subject = (names[0] if names else "tester").lower()
            link = await send_link(interaction.user, watcher.cfg, "test", names[0] if names else "tester",
                                   form_id(store.secret, "test", subject))
        except discord.HTTPException:
            await interaction.followup.send("Couldn't DM you - are DMs from server members on?", ephemeral=True)
        else:
            await interaction.followup.send(f"Sent - check your DMs. The link is:\n{link}", ephemeral=True)

    tree.add_command(mc, guild=guild)
    tree.add_command(admin, guild=guild)


# --- entry point ------------------------------------------------------------------------------------

_watcher: Watcher | None = None


async def attach(client: discord.Client, tree: app_commands.CommandTree) -> None:
    """Called from ZymBot's setup_hook. Anything going wrong is printed and swallowed - the chatbot
    comes up regardless."""
    global _watcher
    try:
        cfg = Config.from_env()
        if cfg is None:
            return
        store = Store(cfg.tz)
        _watcher = Watcher(client, cfg, mc_status.Panel(cfg.panel_url, cfg.panel_key, cfg.server_id), store)
        register_commands(tree, _watcher)
        _watcher.task = asyncio.create_task(_watcher.loop())
    except Exception:
        print("Minecraft sessions: failed to start")
        traceback.print_exc()
        return

    # Per server rather than global, so the commands appear straight away instead of within the hour.
    try:
        await tree.sync(guild=discord.Object(id=cfg.guild_id))
    except discord.HTTPException as exc:
        print(f"Minecraft sessions: couldn't sync /mc commands to server {cfg.guild_id} ({exc}) - the watcher still runs")
