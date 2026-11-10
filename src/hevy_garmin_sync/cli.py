"""The command line. The foundation only reports its version; the app arrives with #1."""

import argparse
import sys
from collections.abc import Sequence

from . import __version__


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hevy-garmin-sync",
        description="Keep Hevy routines and Hevy Trainer workouts on your Garmin watch as strength workouts.",
    )
    p.add_argument("--version", action="version", version=f"hevy-garmin-sync {__version__}")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser().parse_args(argv)
    # Nothing to run yet: the sync itself is built in #1. Saying so beats
    # exiting silently, so a deployment of this version explains itself.
    print(f"hevy-garmin-sync {__version__}: nothing to run yet (zimmertr/hevy-garmin-sync#1)", file=sys.stderr)
    return 0
