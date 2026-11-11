"""The failures the app tells apart. Hevy and Garmin fail in the same four ways (spec O-1, F-16)."""


class ConfigError(Exception):
    """Bad or missing configuration, or a credential a service rejected: the app exits 1, naming the fix (O-1)."""


class Stopped(Exception):
    """The app was told to stop, so no new write to Garmin starts (spec O-3a)."""


class ServiceError(Exception):
    """A call to Hevy or Garmin failed."""


class Rejected(ServiceError):
    """The service refused the credentials (401, 403). Fixed by the user, not by waiting, so the app exits (O-1)."""


class RateLimited(ServiceError):
    """The service said to slow down (429)."""


class Unavailable(ServiceError):
    """Unreachable, timed out, or a server error. Worth retrying."""


class Refused(ServiceError):
    """The service refused this one request (another 4xx). Retrying the same request won't help."""


class NotFound(Refused):
    """What the request named does not exist (404)."""
