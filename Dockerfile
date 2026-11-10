# Tag and digest, so an upstream rebuild of 3.14-slim reaches this image as a
# Dependabot PR rather than silently at the next build.
FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f

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

ENTRYPOINT ["python3", "-m", "hevy_garmin_sync"]
