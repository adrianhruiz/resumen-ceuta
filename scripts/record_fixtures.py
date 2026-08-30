"""Re-record the feed fixtures from the live sources.

Run it when a contract test starts failing, then read the diff: that diff is
the drift the contract test was there to catch.

    uv run python scripts/record_fixtures.py
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

from resumen.feeds import SOURCES, fetch

DESTINATION = Path(__file__).parent.parent / "tests" / "fixtures" / "feeds"


def main() -> int:
    today = datetime.now(UTC).date().isoformat()
    for source in SOURCES:
        raw = fetch(source)
        path = DESTINATION / f"{source.name}-{today}.xml"
        path.write_bytes(raw)
        print(f"{path.name}: {len(raw)} bytes", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
