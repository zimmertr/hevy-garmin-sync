# Every check CI runs, runnable the same way here. Each target runs in Docker,
# in an image pinned by digest that Renovate moves (yggdrasil's preset);
# nothing installs on the workstation (docs/DEVELOPMENT.md).

PYTHON_IMAGE := python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
TRIVY_IMAGE  := aquasec/trivy:0.76.2@sha256:8f6bb947dbc528902e11f2f5be52f7b519f6a39d5d148f41166f2040499768fb
HADOLINT     := hadolint/hadolint:v2.12.0@sha256:30a8fd2e785ab6176eed53f74769e04f125afb2f74a6c52aef7d463583b6d45e
# The Helm version yggdrasil's chart and release modules install.
HELM_IMAGE   := alpine/helm:4.3.1@sha256:e3f8d5c462d75470fbb1fce79ad5c20063657096d1f98c0fcea869e2600e2e5e
# The helm-unittest image yggdrasil's chart module runs (record 0060 there).
HELM_UNITTEST := helmunittest/helm-unittest:4.3.0-1.2.1@sha256:28ea86c3e0b07f501f0c2e9c08b9f41e240f4a4b571cb5106b36cf0f0607e989
IMAGE        := hevy-garmin-sync:dev
RUN          := docker run --rm -v "$(CURDIR)":/repo -w /repo
DEV          := pip install -q --root-user-action=ignore --require-hashes -r requirements-dev.txt

.PHONY: test test-one lint typecheck lint-docker chart build scan lock upstream-check upstream-update \
  live-check live-cleanup live-check-hevy live-check-notes

# The suite under coverage, with its line and branch report, as the test job
# runs it.
test:
	$(RUN) $(PYTHON_IMAGE) sh -c '$(DEV) && \
	  PYTHONPATH=src python -m coverage run -m unittest discover -s tests && \
	  python -m coverage report'

# One module, for iterating on a failure: make test-one MODULE=tests.test_cli
test-one:
	$(RUN) $(PYTHON_IMAGE) sh -c '$(DEV) && PYTHONPATH=src python -m unittest $(MODULE) -v'

# The Python Lint job's first half: ruff under ruff.toml.
lint:
	$(RUN) $(PYTHON_IMAGE) sh -c '$(DEV) && ruff check .'

# The Python Lint job's second half: mypy under mypy.ini.
typecheck:
	$(RUN) $(PYTHON_IMAGE) sh -c '$(DEV) && mypy'

# The Docker Build job's first step.
lint-docker:
	docker run --rm -i $(HADOLINT) < Dockerfile

# The Chart job: lint, render with the defaults, then the helm-unittest suites
# in the chart's tests/ folder, in the image yggdrasil's chart module runs.
chart:
	$(RUN) --entrypoint sh $(HELM_IMAGE) -c 'helm lint charts/hevy-garmin-sync-helm && \
	  helm template hevy-garmin-sync charts/hevy-garmin-sync-helm >/dev/null'
	$(RUN) $(HELM_UNITTEST) charts/hevy-garmin-sync-helm

build:
	docker build --build-arg APP_COMMIT=$$(git rev-parse HEAD) -t $(IMAGE) .

# The release scan's rules (fixable Critical and High only) against a local
# build. Exits non-zero when it finds one, as the release does. The skip is the
# one rule in yggdrasil's defaults/trivy.yaml, which CI reads: pip's vendored
# SBOM is not inventory. Keep the two the same.
scan: build
	$(RUN) -v /var/run/docker.sock:/var/run/docker.sock $(TRIVY_IMAGE) image \
	  --skip-files '**/pip/_vendor/bom.cdx.json' \
	  --ignore-unfixed --severity CRITICAL,HIGH --exit-code 1 $(IMAGE)

# Not a check: rewrites the two hashed locks (the image's and the tests'), on
# the image's own Python. pip-compile keeps every pin it already has unless
# asked; add --upgrade-package NAME to move one. Renovate recompiles both the
# same way, from the command in each lock's header. pip-tools 7.5.3 wrote
# --no-index into that header, which Renovate refuses to read; 7.6 doesn't.
lock:
	$(RUN) $(PYTHON_IMAGE) sh -c "pip install -q --root-user-action=ignore pip-tools==7.6.2 && \
	  pip-compile -q --generate-hashes --allow-unsafe --strip-extras --output-file=requirements.txt requirements.in && \
	  pip-compile -q --generate-hashes --allow-unsafe --strip-extras --output-file=requirements-dev.txt requirements-dev.in"

# Not checks: the weekly upstream-check.yml run, here. Both fetch Garmin's
# exercise list and Hevy's published API spec, which need no sign-in, and
# compare them with the copies in src/hevy_garmin_sync/data and tests/data.
# The first exits 3 on a
# difference and 2 when a source can't be read; the second rewrites the copies.
upstream-check:
	$(RUN) $(PYTHON_IMAGE) python scripts/check_upstream.py

upstream-update:
	$(RUN) $(PYTHON_IMAGE) python scripts/check_upstream.py --write

# Not checks: one run by hand against TJ's own Hevy and Garmin accounts
# (scripts/live_check.py). Interactive, for the Garmin sign-in and for the
# Hevy key and cookie when they aren't in the environment. The first records
# the replies' shapes into live-check/, puts `HGS check set` on the watch and
# probes Garmin's step cap; the second deletes what it made and the saved
# token. The third reads Hevy alone, with no Garmin sign-in, into
# live-check/recorded-hevy.json. The fourth signs in to Garmin alone and puts
# `HGS check notes` on the watch, to see how a note holding last time's numbers
# reads there (#3).
LIVE := $(RUN) -it -e HEVY_API_KEY -e HEVY_SESSION $(PYTHON_IMAGE) sh -c \
  'pip install -q --root-user-action=ignore --require-hashes -r requirements.txt && \
  PYTHONPATH=src python scripts/live_check.py $$0'

live-check:
	$(LIVE) record

live-cleanup:
	$(LIVE) cleanup

live-check-hevy:
	$(LIVE) record-hevy

live-check-notes:
	$(LIVE) notes
