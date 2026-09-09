import re

from handlers import BOT_COMMANDS

_COMMAND_RE = re.compile(r"^[a-z0-9_]{1,32}$")


def test_bot_commands_match_telegram_constraints():
    assert BOT_COMMANDS, "command list must not be empty"

    seen = set()
    for command, description in BOT_COMMANDS:
        assert _COMMAND_RE.match(command), f"invalid command name: {command!r}"
        assert 1 <= len(description) <= 256, f"invalid description length for {command!r}"
        assert command not in seen, f"duplicate command: {command!r}"
        seen.add(command)
