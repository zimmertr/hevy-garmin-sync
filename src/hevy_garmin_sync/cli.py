"""The command line: no arguments runs the app, `login` signs in to Garmin once (spec A-2), and `sync` asks
the running app for a sync (W-3)."""

import argparse
import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from typing import TextIO

from . import __version__, app, login


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hevy-garmin-sync",
        description="Keep Hevy routines and Hevy Trainer workouts on your Garmin watch as strength workouts.",
    )
    p.add_argument("--version", action="version", version=f"hevy-garmin-sync {__version__}")
    commands = p.add_subparsers(dest="command")
    commands.add_parser("login", help="sign in to Garmin once and print the value for GARMIN_TOKEN")
    sync = commands.add_parser("sync", help="ask the running app to sync now")
    sync.add_argument(
        "--force", action="store_true", help="rewrite every workout, undoing edits made in Garmin Connect"
    )
    return p


def sync(force: bool, env: Mapping[str, str] = os.environ, out: TextIO | None = None) -> int:
    """Ask the app on this machine for a sync, through its API, and say what it answered.

    It never talks to Hevy or Garmin itself: a second process refreshing the
    same Garmin token would lock both out (spec A-7). The image has no curl,
    so this is how a sync is asked for from inside the container.
    """
    port = env.get("HTTP_PORT", "").strip() or "8080"
    url = f"http://127.0.0.1:{port}/api/sync" + ("?force=true" if force else "")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="POST"), timeout=10) as reply:
            answer = json.load(reply)
    except urllib.error.HTTPError as e:
        with e:
            if e.code == 429:
                seconds = json.load(e).get("seconds")
                print(f"A sync ended less than a minute ago. Try again in {seconds} seconds.", file=out)
            elif e.code == 409:
                print(f"No sync can run: {json.load(e).get('reason')}", file=out)
            else:
                print(f"The app refused the request (HTTP {e.code}).", file=out)
        return 1
    except (urllib.error.URLError, OSError):
        print(f"The app isn't running here: nothing answers on port {port}.", file=out)
        return 1
    if answer.get("result") != "joined":
        said = f"{'A forced sync' if force else 'A sync'} has started. The status page shows its progress."
    elif not answer.get("running"):
        # One still waiting to start takes a Force; one that runs has chosen what to write (W-4).
        said = "A sync is waiting to start. Your request joined it" + (", and it is now forced." if force else ".")
    elif force and not answer.get("force"):
        said = "A sync is already running, so --force wasn't applied. Run `sync --force` again once it ends."
    else:
        said = "A sync is already running. Your request joined it."
    print(said, file=out)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "login":
        return login.main()
    if args.command == "sync":
        return sync(args.force)
    return app.main()
