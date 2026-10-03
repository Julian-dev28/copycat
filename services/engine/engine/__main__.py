"""`python -m engine`: runs the worker loop against the real Hyperliquid venue.

Imports `hl.HlVenue` lazily, inside `main()`, not at module import time.
`services/hl` is being built in parallel by another session; `engine`'s own
modules (and its tests) must import cleanly whether or not `services/hl`
exists yet. Only actually running the worker needs it.
"""
from __future__ import annotations

import logging
import os
import sys


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    logging.basicConfig(
        level=os.environ.get("COPYCAT_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("engine")

    our_address = os.environ.get("COPYCAT_ACCOUNT_ADDRESS")
    if not our_address:
        logger.error("COPYCAT_ACCOUNT_ADDRESS is not set, refusing to start")
        sys.exit(1)

    from hl import HlVenue  # services/hl, built in parallel -- see module docstring

    from .public import run_forever

    logger.info("engine starting, account=%s", our_address)
    run_forever(HlVenue())


if __name__ == "__main__":
    main()
