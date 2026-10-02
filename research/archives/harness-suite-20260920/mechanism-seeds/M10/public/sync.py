def apply_messages(messages):
    """Apply messages in arrival order (seeded implementation has regressions)."""
    state = {}
    for message in messages:
        if message.get("deleted"):
            state.pop(message["id"], None)
        else:
            state[message["id"]] = {
                "version": message["version"],
                "value": message["value"],
            }
    return state
