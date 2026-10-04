"""CLI.

    python -m discovery.thesis 0xADDR [--days 30] [--refresh] [--markdown]

Prints the templated summary, the tags and the caveats (or the full `ta`
thesis markdown with --markdown). HL reads use the background priority.
"""
from __future__ import annotations

import argparse
import sys

from . import public


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="discovery.thesis", description="Deterministic strategy fingerprint.")
    p.add_argument("address")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--refresh", action="store_true", help="ignore the stored fingerprint's TTL")
    p.add_argument("--markdown", action="store_true", help="print the full ta thesis markdown")
    a = p.parse_args(argv)
    try:
        fp = public.fingerprint(a.address, a.days, refresh=a.refresh)
    except (ValueError, public.ThesisError) as exc:
        print(f"thesis: {exc}", file=sys.stderr)
        return 1
    if a.markdown:
        print(public.ta_thesis(a.address, fingerprint=fp).markdown)
        return 0
    print(f"{fp.address}  {fp.window_days}d  {fp.trips_analyzed} trips  style={fp.style.value if fp.style else '-'}")
    print()
    print(fp.summary)
    print()
    print("tags: " + (", ".join(fp.tags) or "-"))
    for c in fp.caveats:
        print(f"caveat: {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
