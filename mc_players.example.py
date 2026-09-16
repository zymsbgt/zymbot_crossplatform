"""
Who plays on the CivFabric server, and which Discord account gets their feedback.

Copy this file to mc_players.py and fill it in. mc_players.py is not committed, because it names real
people - upload it to the bot's Pterodactyl volume the same way .env gets there.

Hardcoded rather than collected by a /link command: the playerbase is a few small friend groups who
are all known in advance, and a command nobody remembers to run means a session ends with nobody left
to ask.

Names are matched case-insensitively. A UUID entry is checked first, and is worth adding for anyone
who might rename themselves - a rename breaks a name entry silently, while a UUID never changes. Read
a UUID from https://api.mojang.com/users/profiles/minecraft/<name> or the server's usercache.json.

Discord user ids: Settings > Advanced > Developer Mode, then right-click somebody > Copy User ID.

/mc-admin players lists the table and re-reads this file, so adding somebody needs no restart.
"""

# "Minecraft name": {"discord": <Discord user id>, "uuid": "<optional, from usercache.json>"}
# A bare "Minecraft name": <Discord user id> works too. An entry holding 0 is skipped and logged.
PLAYERS = {
    "ZymSB": {"discord": 111111111111111111, "uuid": "4566e69f-c907-48ee-8d71-d7ba5aa00d20"},
    "Player_2": 222222222222222222,
}

# Extra UUIDs for anybody who plays on a second account, as "uuid": <Discord user id>.
UUIDS = {
}
