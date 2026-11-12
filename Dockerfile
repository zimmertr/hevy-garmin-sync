# Tag and digest, so an upstream rebuild of 3.15-slim reaches this image as a
# Renovate PR rather than silently at the next build.
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DATA_DIR=/data

WORKDIR /app
# The hashed lock, installed with every hash checked.
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

COPY LICENSE /app/LICENSE
COPY src/hevy_garmin_sync /app/hevy_garmin_sync

# The one folder the app writes to (spec C-8), owned by the user it runs as, so
# a fresh volume mounted here is writable.
RUN mkdir /data && chown 1000:1000 /data

ARG APP_VERSION=0.0.0+dev
ENV APP_VERSION=${APP_VERSION}

# The base image lags Debian's security fixes, and the release scan refuses a
# fixable High. The upgrade sits after APP_COMMIT, which changes on every
# build: BuildKit keys a RUN on every build argument in scope, so a layer cache
# can't freeze this layer and keep a fixed CVE out. Only USER and ENTRYPOINT
# follow it.
ARG APP_COMMIT=unknown
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

USER 1000:1000

# The status page, on HTTP_PORT (spec W-1, C-13).
EXPOSE 8080

ENTRYPOINT ["python3", "-m", "hevy_garmin_sync"]
