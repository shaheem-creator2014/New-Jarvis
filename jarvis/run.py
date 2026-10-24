"""Launch the local JARVIS application."""
import sys
if sys.version_info < (3, 11):
    raise SystemExit("JARVIS requires Python 3.11 or newer")
from agent.main import main
if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, PermissionError, OSError) as error:
        raise SystemExit(f"JARVIS: {error}")
