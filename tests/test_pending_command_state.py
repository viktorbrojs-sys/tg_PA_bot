from services.pending_command_state import PendingCommandState


def test_pending_command_state_lifecycle():
    state = PendingCommandState()
    assert not state.is_pending(1)

    state.start(1, "search")
    assert state.is_pending(1)
    assert not state.is_pending(2)

    assert state.pop(1) == "search"
    assert not state.is_pending(1)
    assert state.pop(1) is None  # already consumed


def test_pending_command_state_clear():
    state = PendingCommandState()
    state.start(1, "done")
    state.clear(1)
    assert not state.is_pending(1)
    assert state.pop(1) is None


def test_pending_command_state_overwrites_previous_command():
    state = PendingCommandState()
    state.start(1, "search")
    state.start(1, "plan")  # a new command supersedes the old prompt
    assert state.pop(1) == "plan"
