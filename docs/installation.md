# Installation

[中文版](zh-CN/installation.md)

## Requirements

- **Python**: 3.9 or newer (structchunk uses `from __future__ import annotations` and `int | str` union syntax only in type hints, so it works on 3.9+)
- **Operating system**: any (pure-Python, no platform-specific code; the optional `os.register_at_fork` is a no-op on platforms that lack it)
- **Disk space**: under 1 MB

## Install from PyPI

The simplest way for most users:

```bash
pip install structchunk
```

## Install from source

Use this when you want the latest unreleased code or want to modify structchunk:

```bash
git clone https://github.com/yzp0111/structchunk.git
cd structchunk
pip install -e ".[test]"
```

The `[test]` extra installs `pytest>=7.0` so you can run the test suite locally.

## Install with uv

[uv](https://github.com/astral-sh/uv) is a fast Python package manager. If you have it installed:

```bash
uv pip install structchunk
```

Or to install from source in a uv-managed virtual environment:

```bash
git clone https://github.com/yzp0111/structchunk.git
cd structchunk
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[test]"
```

## Verify Installation

After installing, confirm the package imports and the version is reported:

```bash
python -c "import structchunk; print(structchunk.__version__)"
```

Expected output: `0.1.0`

You can also verify the CLI is available:

```bash
structchunk --help
```

## Optional: Build from source

To build a wheel and sdist yourself (e.g. for offline installation):

```bash
git clone https://github.com/yzp0111/structchunk.git
cd structchunk
python -m pip install build
python -m build
```

This produces a `dist/` directory with `structchunk-0.1.0-py3-none-any.whl` and `structchunk-0.1.0.tar.gz`. Install the wheel with:

```bash
pip install dist/structchunk-0.1.0-py3-none-any.whl
```

## Next Steps

- [Quick Start](quickstart.md) — your first chunk
- [Algorithms](algorithms.md) — which algorithm to pick
- [API Reference](api.md) — every public function, class, and configuration field
