"""The command line: no arguments runs the app, `login` signs in to Garmin once (spec A-2)."""

import argparse
import sys
from collections.abc import Sequence

from . import __version__, login


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hevy-garmin-sync",
        description="Keep Hevy routines and Hevy Trainer workouts on your Garmin watch as strength workouts.",
    )
    p.add_argument("--version", action="version", version=f"hevy-garmin-sync {__version__}")
    commands = p.add_subparsers(dest="command")
    commands.add_parser("login", help="sign in to Garmin once and print the value for GARMIN_TOKEN")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "login":
        return login.main()
    # Nothing to run yet: the sync itself is built in #1. Saying so beats
    # exiting silently, so a deployment of this version explains itself.
    print(f"hevy-garmin-sync {__version__}: nothing to run yet (zimmertr/hevy-garmin-sync#1)", file=sys.stderr)
    return 0
