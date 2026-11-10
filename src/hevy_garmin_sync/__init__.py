"""Turn Hevy routines and Hevy Trainer workouts into Garmin Connect strength workouts."""

import os

# The release bakes its version into the image as APP_VERSION (yggdrasil's
# release module passes it as a build argument). A run from a clone has none.
__version__ = os.environ.get("APP_VERSION", "0.0.0+dev")
