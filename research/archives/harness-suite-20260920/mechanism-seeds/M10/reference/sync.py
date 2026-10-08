def apply_messages(messages):
    state = {}
    for message in messages:
        previous = state.get(message["id"])
        if previous is not None and message["version"] <= previous["version"]:
            continue
        if message.get("deleted"):
            state.pop(message["id"], None)
        else:
            state[message["id"]] = {"version": message["version"], "value": message["value"]}
    return state
