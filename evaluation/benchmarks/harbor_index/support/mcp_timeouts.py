"""Transport margins preserve the pinned ARE notification wait contract."""

import math


def transport_timeouts(tool, arguments):
    # The pinned official ARE server allows 4x simulated seconds of wall time,
    # with a 30-second floor. Transport layers must expire after that server
    # boundary, rather than truncate a legitimate 300-second notification wait.
    operation = 300
    if tool == "are_wait_for_notification":
        seconds = arguments.get("timeout_seconds", 180)
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            seconds = 180
        if not math.isfinite(seconds) or seconds < 0:
            seconds = 180
        operation = max(operation, math.ceil(max(30, seconds * 4)))
    # Mailbox publication can spend 3 x 45 seconds in bounded I/O recovery.
    return operation + 30, operation + 210, operation + 240
