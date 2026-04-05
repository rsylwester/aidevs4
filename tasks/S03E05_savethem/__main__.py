"""S03E05 - savethem: Route planning orchestrator agent for Skolwin mission."""

from __future__ import annotations

from tasks.S03E05_savethem.solve import main

if __name__ == "__main__":
    from lib.logging import setup_logging

    setup_logging()
    main()
