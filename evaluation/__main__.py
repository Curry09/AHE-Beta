"""Single public entry point for held-out Harbor evaluation."""

import sys

from .cli import main
from .config import PlanError

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PlanError, ValueError) as error:
        print(f"Evaluation error: {error}", file=sys.stderr)
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        print("Controller detached. Existing workers continue; use resume with the same run root.")
        raise SystemExit(130) from None
