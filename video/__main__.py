"""Entry: python3 -m video (from /app with PYTHONPATH)."""

from __future__ import annotations

import logging
import os

from video.telemetry import run


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    run()


if __name__ == "__main__":
    main()
