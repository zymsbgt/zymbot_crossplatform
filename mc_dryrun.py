"""
Checks the unattended-session setup without touching anything.

Read-only by design: it asks the panel for state and reads files, and never sends a console command,
a power action or a DM. Safe to run while players are on.

    python mc_dryrun.py

Best run where ZymBot itself runs, because two of these checks are really about that machine: whether
the panel answers from there, and whether the Minecraft port does. Run it from anywhere else and a
ping failure may only mean your own network.

Nothing here prints the API key, the bot token or the form secret.
"""

from __future__ import annotations

import asyncio
import csv
import io
import sys

import mc_sessions
import mc_status

try:
    from dotenv import load_dotenv
except ImportError:
    # Only the bot host needs dotenv installed. Elsewhere, real environment variables still work.
    def load_dotenv():
        print("(python-dotenv not installed, so .env is not read - using the environment as it is)")

load_dotenv()

problems = []


def ok(label, detail=""):
    print(f"  ok   {label}" + (f" - {detail}" if detail else ""))


def bad(label, detail=""):
    problems.append(label)
    print(f"  FAIL {label}" + (f" - {detail}" if detail else ""))


def note(label):
    print(f"       {label}")


async def main():
    print("== config ==")
    cfg = mc_sessions.Config.from_env()
    if cfg is None:
        bad("required .env keys missing", "see the list printed above")
        return
    ok("config loaded", f"{cfg.address}, panel {cfg.panel_url}, server {cfg.server_id}")
    note(f"stop at {cfg.threshold} or fewer for {int(cfg.grace / 60)}m, "
         f"warning {int(cfg.warn / 60)}m before, no-show {int(cfg.no_show / 60)}m, "
         f"end time {cfg.hard_stop or 'none'} ({cfg.tz})")

    print()
    print("== players ==")
    store = mc_sessions.Store(cfg.tz)
    if not store.players:
        bad("mc_players.py has nobody in it", "every entry still holds 0, or the file is missing")
    else:
        accounts = {entry["discord"] for entry in store.players.values()}
        ok(f"{len(store.players)} names, {len(store.uuids)} uuids, {len(accounts)} Discord accounts")
    note("the form secret is " + ("from MC_FORM_SECRET" if __import__("os").getenv("MC_FORM_SECRET", "").strip()
                                  else f"kept in {store.secret_file}"))

    print()
    print("== feedback form ==")
    if not cfg.form_url:
        bad("MC_FORM_URL is not set", "the server would still be stopped, but nobody would be asked")
    else:
        missing = [key for key in ("{form_id}", "{name}", "{discord}") if key not in cfg.form_url]
        if "{form_id}" in missing and "{session}" not in cfg.form_url:
            bad("MC_FORM_URL says nothing about the session", "add {form_id} or {session}")
        elif missing:
            ok("MC_FORM_URL usable", f"not filling: {', '.join(missing)}")
        else:
            ok("MC_FORM_URL has every placeholder")
        if store.players:
            name = sorted(e["name"] for e in store.players.values())[0]
            sample = mc_sessions.form_id(store.secret, "dryrun-000000", name.lower())
            note("sample link: " + mc_sessions.form_link(cfg.form_url, "dryrun-000000", name, "discord_handle", sample))

    print()
    print("== panel ==")
    panel = mc_status.Panel(cfg.panel_url, cfg.panel_key, cfg.server_id)
    try:
        await panel_checks(panel, cfg, store)
    finally:
        # Whatever went wrong above, the HTTP session still has to be closed.
        await panel.close()

    print()
    print("== minecraft port ==")
    await port_check(cfg, panel_state["state"])

    print()
    if problems:
        print(f"{len(problems)} to fix: " + "; ".join(problems))
    else:
        print("All checks passed. The live test left is: start the server, join, leave, and watch it stop.")
    return 1 if problems else 0


panel_state = {"state": None}


async def panel_checks(panel, cfg, store):
    state = None
    try:
        state = await panel.state()
        ok("panel reachable, key accepted", f"server is {state}")
        panel_state["state"] = state
    except mc_status.PANEL_ERRORS as exc:
        bad("panel call failed", str(exc))
        note("401 or 403: the key or its subuser permissions. 404: PTERO_SERVER_ID.")

    level = "world"
    if state is not None:
        try:
            properties = mc_sessions.parse_properties(await panel.read_file("/server.properties"))
            level = properties.get("level-name") or "world"
            ok("server.properties read", f"level-name={level}, server-port={properties.get('server-port', '?')}")
            if properties.get("server-port") and cfg.port != int(properties["server-port"]):
                bad("MC_PORT does not match server-port", f"{cfg.port} vs {properties['server-port']}")
        except mc_status.PANEL_ERRORS + (ValueError,) as exc:
            bad("could not read server.properties", str(exc))

        try:
            present = await panel.list_dir(f"/{level}/datapacks")
            if not cfg.datapack:
                ok("datapack check switched off")
            elif cfg.datapack in present or f"{cfg.datapack}.zip" in present:
                ok("datapack present", f"{level}/datapacks/{cfg.datapack}")
            else:
                bad("datapack missing", f"{level}/datapacks holds: {', '.join(sorted(present)) or 'nothing'}")
        except mc_status.PANEL_ERRORS as exc:
            bad("could not list the datapacks folder", str(exc))

        try:
            rows = list(csv.DictReader(io.StringIO(await panel.read_file("/civfabric-logs/sessions.csv"))))
            if rows:
                last = rows[-1]
                ok("telemetry readable", f"last boot {last.get('session')}, CivFabric {last.get('mod_version')}, "
                                         f"{last.get('slots')} slots, {last.get('classes')} classes")
            else:
                bad("sessions.csv has no rows yet", "it is written when the server next starts")
        except mc_status.PANEL_ERRORS as exc:
            bad("could not read civfabric-logs/sessions.csv", f"{exc} - feedback would use a bot-side run id")

        try:
            text = await panel.read_file("/logs/latest.log")
            names = mc_status.joined_names(text)
            ok("latest.log readable", f"{len(text) // 1024} KB, joins seen: {', '.join(sorted(names)) or 'none'}")
            unknown = [n for n in names if store.owner(n) is None]
            if unknown:
                note(f"played but not in mc_players.py: {', '.join(sorted(unknown))}")
        except mc_status.PANEL_ERRORS as exc:
            bad("could not read logs/latest.log", str(exc))


async def port_check(cfg, state):
    status = await mc_status.ping(cfg.host, cfg.port, timeout=8)
    if status is not None:
        ok("server answered a status ping", f"{status.online}/{status.max} online"
           + (f", sampled: {', '.join(sorted(status.names))}" if status.names else ", no names sampled"))
    elif state == "running":
        bad("server is running but did not answer a status ping",
            f"{cfg.host}:{cfg.port} unreachable from here, so the stop rule would never see a player count")
    else:
        ok("no answer, which is expected", f"the panel says the server is {state or 'unknown'}")


sys.exit(asyncio.run(main()) or 0)
