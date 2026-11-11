# Every check CI runs, runnable the same way here. Each target runs in Docker;
# nothing installs on the workstation (docs/DEVELOPMENT.md).

PYTHON_IMAGE := python:3.14-slim
TRIVY_IMAGE  := aquasec/trivy:0.68.1
HADOLINT     := hadolint/hadolint:v2.12.0
# The Helm version pr.yml and release.yml install; move them together.
HELM_IMAGE   := alpine/helm:4.3.0
IMAGE        := hevy-garmin-sync:dev
RUN          := docker run --rm -v "$(CURDIR)":/repo -w /repo
DEV          := pip install -q --root-user-action=ignore --require-hashes -r requirements-dev.txt

.PHONY: test test-one lint typecheck lint-docker chart build scan lock

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

# The Chart job: lint, render with the defaults and with an existing Secret,
# then check that all three default resources state their namespace and that
# the container's root filesystem is read-only.
chart:
	$(RUN) --entrypoint sh $(HELM_IMAGE) -c 'helm lint charts/hevy-garmin-sync-helm && \
	  helm template hevy-garmin-sync charts/hevy-garmin-sync-helm >/dev/null && \
	  helm template hevy-garmin-sync charts/hevy-garmin-sync-helm --set existingSecret=hevy-garmin-sync >/dev/null && \
	  test "$$(helm template hevy-garmin-sync charts/hevy-garmin-sync-helm --namespace check | grep -c "^  namespace: check$$")" -eq 3 && \
	  helm template hevy-garmin-sync charts/hevy-garmin-sync-helm | grep -q "^            readOnlyRootFilesystem: true$$"'

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
# asked; add --upgrade-package NAME to move one. The pip-tools and pip versions
# are hevy-trainer-sync's, the pair Dependabot also runs.
lock:
	$(RUN) $(PYTHON_IMAGE) sh -c "pip install -q --root-user-action=ignore 'pip<26' pip-tools==7.5.3 && \
	  pip-compile -q --generate-hashes --allow-unsafe --strip-extras --output-file=requirements.txt requirements.in && \
	  pip-compile -q --generate-hashes --allow-unsafe --strip-extras --output-file=requirements-dev.txt requirements-dev.in"
