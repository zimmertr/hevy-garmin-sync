"""The command line: no arguments runs the app, `login` signs in to Garmin once (spec A-2)."""

import argparse
from collections.abc import Sequence

from . import __version__, app, login


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
    return app.main()
