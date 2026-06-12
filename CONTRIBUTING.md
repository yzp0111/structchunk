# Contributing to structchunk

Thanks for your interest in structchunk. This guide will help you get started with contributing, whether you're fixing a bug, adding a feature, or improving documentation.

## Introduction

structchunk is a single-author, pure-Python library with zero runtime dependencies. The codebase is small (under 2,000 lines) and well-separated into focused modules. New contributors should find it easy to navigate once they understand the module layout and the two algorithm strategies.

## Code of Conduct

This project follows a Contributor Code of Conduct. By participating, you agree to uphold it. Read the full text in [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Getting Started

Fork the repository on GitHub, then clone your fork:

```bash
git clone https://github.com/your-username/structchunk.git
cd structchunk
```

Install the package in editable mode with test dependencies:

```bash
pip install -e ".[test]"
```

Verify everything works:

```bash
pytest
```

All 192 tests should pass. If not, check your Python version (requires >= 3.9) and that pytest >= 7.0 is installed.

## Project Layout

```
src/structchunk/
├── __init__.py         # public API: chunk, chunk_file, chunk_to_dicts
├── _version.py         # __version__
├── _config.py          # ChunkerConfig
├── _models.py          # AtomicBlock, BlockType, MarkdownChunk, ChunkMetadata
├── _parser.py          # _parse_atomic_blocks, regex constants
├── _splitters.py       # sentence / table / list / code sub-splitters
├── _enrich.py          # breadcrumb, RAG metadata
├── linear.py           # linear (greedy) chunker
├── hierarchical.py     # hierarchical (tree) chunker
└── _cli.py             # CLI entry point
examples/
└── basic.py            # basic usage demo (both algorithms)
tests/                  # pytest test suite
```

The core chunking logic lives in `linear.py` and `hierarchical.py`. The private modules under `src/structchunk/_*.py` handle parsing, model definitions, and text splitting. The `examples/` directory shows usage patterns, and `tests/` has the full test suite.

## Development Workflow

Create a feature branch from `master`:

```bash
git checkout -b feat/your-feature-name
```

Make your changes. Write tests if you're adding functionality. Run the test suite often:

```bash
pytest
```

When you're ready, push the branch and open a pull request against `master`.

A few workflow rules:

- Branch from `master`, not from another feature branch.
- One feature or fix per branch. If you find yourself working on two unrelated things, split them.
- Keep commits small and focused. No need to squash before review -- we can do that on merge.

## Coding Style

- Follow PEP 8. 120-character line limit preferred (the existing code uses 120).
- All public API functions and classes must have type hints.
- Write Google-style docstrings for public functions: one-line summary, then Args: and Returns: sections when applicable.
- Private functions (prefixed with `_`) should have a docstring if their logic is non-trivial.
- Avoid external runtime dependencies. structchunk is pure Python with zero runtime deps.
- Use meaningful variable names. Single-letter names are only acceptable in short comprehensions or lambda expressions.

## Testing

Tests live in the `tests/` directory and use pytest. Run the full suite from the project root:

```bash
pytest
```

All 192 tests must pass before a pull request is merged. If you add a new feature, include tests covering:

- Normal cases (the feature works as expected).
- Edge cases (empty input, single element, maximum sizes).
- Error cases (invalid arguments, unsupported formats).

To run a specific test file:

```bash
pytest tests/test_structchunk.py -v
```

The only test dependency is `pytest>=7.0`, declared under `[project.optional-dependencies] test` in `pyproject.toml`.

## Documentation

When you change a user-facing feature (public API, CLI flags, algorithm behavior), update both documentation locations:

1. **English (canonical)**: the primary docs in `README.md` and any related docstrings.
2. **Chinese (mirror)**: the zh-CN translation if one exists.

After updating, verify heading parity between the two versions:

```bash
python scripts/check_doc_sync.py
```

This script checks that every heading in the English version has a matching heading in the Chinese version. If it reports mismatches, fix them before committing. Out-of-sync docs will be held up in review.

## Submitting a Pull Request

Before opening a PR, go through this checklist:

- [ ] The branch targets `master`.
- [ ] All 192 tests pass (`pytest` from project root).
- [ ] New features include tests.
- [ ] Public APIs have type hints and Google-style docstrings.
- [ ] User-facing changes are reflected in both EN and zh-CN docs.
- [ ] `python scripts/check_doc_sync.py` reports no mismatches.
- [ ] The change is scoped to one feature or fix (no scope creep).

Link any related issues in the PR description using GitHub keywords like `Closes #123` or `Related to #456`.

Keep PRs focused. A PR that fixes a bug, refactors a module, and adds a feature all at once is hard to review. Split it up.

## Reporting Bugs

Open a [GitHub issue](https://github.com/yzp0111/structchunk/issues) and use the `bug_report.md` template. Include:

- A clear, descriptive title.
- Steps to reproduce the bug.
- What you expected to happen vs what actually happened.
- The structchunk version (`pip show structchunk`), Python version, and OS.
- A minimal code snippet or input document that triggers the bug, if possible.

## Suggesting Features

Open a [GitHub issue](https://github.com/yzp0111/structchunk/issues) and use the `feature_request.md` template. Describe:

- What problem the feature would solve.
- How you imagine the API or behavior would work.
- Any prior art or references (other chunkers, papers, tools) that inspired the idea.

Feature requests are welcome. Not every suggestion will be implemented, but each one gets a fair read.

## Questions

For questions, usage help, or open-ended discussions, use [GitHub Discussions](https://github.com/yzp0111/structchunk/discussions) with the `question.md` template. This is the right place for "how do I..." and "what's the best way to..." type questions.

If your question is about a specific bug or feature request, file an issue instead.
