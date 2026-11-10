"""The one-off Garmin sign-in (spec A-2): prompt, sign in, print the value of GARMIN_TOKEN.

Run on the user's own machine. The password goes to python-garminconnect once
and is written nowhere; the app itself only ever sees the token.
"""

import getpass
import sys
from typing import TextIO

import garminconnect

from .garmin import encode_token


def sign_in() -> str:
    """Sign in to Garmin and return the value for GARMIN_TOKEN."""
    email = input("Garmin email: ")
    password = getpass.getpass("Garmin password (not shown, not saved): ")
    api = garminconnect.Garmin(email, password, prompt_mfa=lambda: input("Garmin 2FA code: "), retry_attempts=0)
    # No token store: the library saves nothing, and the token leaves only as the printed value.
    api.login()
    return encode_token(api.client.dumps())


def main(out: TextIO = sys.stdout, err: TextIO = sys.stderr) -> int:
    try:
        token = sign_in()
    except garminconnect.GarminConnectTooManyRequestsError:
        print("Garmin is refusing sign-ins for now (too many attempts). Wait an hour and try again.", file=err)
        return 1
    except (garminconnect.GarminConnectAuthenticationError, garminconnect.GarminConnectConnectionError) as e:
        print(f"Sign-in failed: {e}", file=err)
        print("If this machine is a cloud server, Garmin may be blocking it: run `login` from home.", file=err)
        return 1
    print("\nSigned in. Set GARMIN_TOKEN to this value and keep it secret:\n", file=err)
    print(token, file=out)
    return 0
