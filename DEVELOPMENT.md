# Development

## Local Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .[dev,web]
```

Run the unittest suite:

```bash
python3 -m unittest discover -s tests -q
```

## Workspace-Oriented Manual Testing

Create a fresh workspace and start from the same flow users will see:

```bash
offerquest init-workspace --path /tmp/offerquest-workspace
cd /tmp/offerquest-workspace
offerquest doctor --path .
offerquest-workbench --root .
```

## Release Artifacts

Install the release tooling when you need to build distributable artifacts:

```bash
pip install -e .[release]
```

Build an sdist and wheel:

```bash
./scripts/build-release.sh
```

Run the release smoke test workflow in clean virtual environments:

```bash
./scripts/smoke-test-install.sh
```

The smoke test expects the release tooling to be installed and may need network access for optional web dependencies, depending on the environment.
