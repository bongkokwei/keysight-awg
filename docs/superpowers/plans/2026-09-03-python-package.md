# Python Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap the keysight_awg project into an installable Python package using modern `pyproject.toml` + src layout.

**Architecture:** The six existing flat modules become a `keysight_awg` package under `src/keysight_awg/`. Core library code (the M8195A driver, high-level tools, and multitone generator) lives inside the package with relative imports. Standalone scripts (demo, stop, connection test) move to `examples/` and import the installed package. A thin `__init__.py` re-exports the primary public API so users can write `from keysight_awg import M8195A`.

**Tech Stack:** Python >= 3.10, numpy (runtime dependency), matplotlib (optional dependency for plotting examples), setuptools build backend via `pyproject.toml`.

## Global Constraints

- Python >= 3.10 (uses `from __future__ import annotations` and `list[str]` return annotations already present in the code).
- numpy is the only hard runtime dependency.
- matplotlib is an optional extra (`pip install keysight_awg[plot]`).
- No VISA/pyvisa dependency — the driver uses raw TCP sockets.
- Waveform granularity constants (256/128/64) are hardware-defined; do not change them.
- All SCPI communication goes through port 5025 over raw TCP.

---

### Task 1: Create package scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/keysight_awg/__init__.py`
- Create: `.gitignore`

**Interfaces:**
- Consumes: nothing
- Produces: an installable package skeleton (no code yet) that `pip install -e .` accepts without error.

- [ ] **Step 1: Write a test that verifies the package metadata is importable**

Create a minimal test that will pass once the package is installable:

```python
# tests/test_package.py
import importlib.metadata

def test_package_is_installed():
    meta = importlib.metadata.metadata("keysight_awg")
    assert meta["Name"] == "keysight_awg"

def test_version_is_set():
    meta = importlib.metadata.metadata("keysight_awg")
    assert meta["Version"] == "0.1.0"
```

Also create the test directory marker:

```python
# tests/__init__.py
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `python -m pytest tests/test_package.py -v`
Expected: FAIL — `importlib.metadata.PackageNotFoundError` because the package is not installed.

- [ ] **Step 3: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68.0", "setuptools-scm"]
build-backend = "setuptools.build_meta"

[project]
name = "keysight_awg"
version = "0.1.0"
description = "Python driver for the Keysight M8195A 65 GSa/s Arbitrary Waveform Generator"
readme = "README.md"
requires-python = ">=3.10"
license = "MIT"
dependencies = [
    "numpy>=1.24",
]

[project.optional-dependencies]
plot = ["matplotlib>=3.7"]
dev = ["pytest>=7.0"]

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 4: Create `src/keysight_awg/__init__.py`**

This is a placeholder that will be filled in Task 3 once the modules are moved. For now it just defines `__version__`:

```python
"""Keysight M8195A AWG driver package."""

__version__ = "0.1.0"
```

- [ ] **Step 5: Create `.gitignore`**

```gitignore
__pycache__/
*.pyc
*.pyo
*.egg-info/
dist/
build/
.eggs/
*.egg
.venv/
venv/
.pytest_cache/
```

- [ ] **Step 6: Install in editable mode**

Run: `pip install -e ".[dev]"`
Expected: installs successfully, prints "Successfully installed keysight_awg-0.1.0"

- [ ] **Step 7: Run the test to confirm it passes**

Run: `python -m pytest tests/test_package.py -v`
Expected: PASS — both `test_package_is_installed` and `test_version_is_set` pass.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src/keysight_awg/__init__.py .gitignore tests/__init__.py tests/test_package.py
git commit -m "feat: add package scaffolding with pyproject.toml and src layout"
```

---

### Task 2: Move core modules into the package

**Files:**
- Move: `m8195a.py` → `src/keysight_awg/m8195a.py`
- Move: `m8195a_tools.py` → `src/keysight_awg/tools.py`
- Move: `multitone_generator.py` → `src/keysight_awg/multitone.py`

**Interfaces:**
- Consumes: package skeleton from Task 1
- Produces: `keysight_awg.m8195a.M8195A`, `keysight_awg.tools.*`, `keysight_awg.multitone.*` — all importable from the installed package.

- [ ] **Step 1: Write tests that verify the core classes are importable**

```python
# tests/test_imports.py
def test_import_m8195a_class():
    from keysight_awg.m8195a import M8195A
    assert callable(M8195A)

def test_import_tools():
    from keysight_awg.tools import configure_single_channel, load_and_play, generate_sine
    assert callable(configure_single_channel)
    assert callable(load_and_play)
    assert callable(generate_sine)

def test_import_multitone():
    from keysight_awg.multitone import MultiToneGenerator, ToneSpec
    assert callable(MultiToneGenerator)
    assert callable(ToneSpec)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_imports.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'keysight_awg.m8195a'`

- [ ] **Step 3: Move `m8195a.py` into the package**

Copy the file with no content changes:

```bash
cp m8195a.py src/keysight_awg/m8195a.py
```

- [ ] **Step 4: Move `m8195a_tools.py` into the package as `tools.py`**

Copy the file:

```bash
cp m8195a_tools.py src/keysight_awg/tools.py
```

- [ ] **Step 5: Move `multitone_generator.py` into the package as `multitone.py`**

Copy the file:

```bash
cp multitone_generator.py src/keysight_awg/multitone.py
```

- [ ] **Step 6: Fix the internal import in `src/keysight_awg/tools.py`**

Change the import at line 21 from:

```python
from m8195a import M8195A
```

to:

```python
from keysight_awg.m8195a import M8195A
```

No other files have cross-module imports that need changing (`multitone.py` and `m8195a.py` are self-contained).

- [ ] **Step 7: Update `src/keysight_awg/__init__.py` to re-export the public API**

```python
"""Keysight M8195A AWG driver package."""

__version__ = "0.1.0"

from keysight_awg.m8195a import M8195A
from keysight_awg.multitone import MultiToneGenerator, ToneSpec
from keysight_awg.tools import configure_single_channel, generate_sine, load_and_play

__all__ = [
    "M8195A",
    "MultiToneGenerator",
    "ToneSpec",
    "configure_single_channel",
    "generate_sine",
    "load_and_play",
]
```

- [ ] **Step 8: Reinstall the package in editable mode**

Run: `pip install -e ".[dev]"`
Expected: installs successfully.

- [ ] **Step 9: Run all tests to verify imports work**

Run: `python -m pytest tests/ -v`
Expected: all tests in `test_package.py` and `test_imports.py` PASS.

- [ ] **Step 10: Commit**

```bash
git add src/keysight_awg/m8195a.py src/keysight_awg/tools.py src/keysight_awg/multitone.py src/keysight_awg/__init__.py tests/test_imports.py
git commit -m "feat: move core modules into keysight_awg package"
```

---

### Task 3: Add a top-level import convenience test

**Files:**
- Create: `tests/test_top_level_api.py`

**Interfaces:**
- Consumes: re-exports from `__init__.py` (Task 2, Step 7)
- Produces: verified top-level `from keysight_awg import M8195A` API

- [ ] **Step 1: Write the test**

```python
# tests/test_top_level_api.py
def test_top_level_import_m8195a():
    from keysight_awg import M8195A
    assert M8195A.SCPI_PORT == 5025

def test_top_level_import_multitone():
    from keysight_awg import MultiToneGenerator, ToneSpec
    import numpy as np
    gen = MultiToneGenerator(sample_rate=1e9, granularity=256)
    tones = [ToneSpec(frequency=1e6, amplitude=0.5)]
    waveform = gen.generate(tones)
    assert isinstance(waveform, np.ndarray)
    assert len(waveform) % 256 == 0

def test_top_level_import_tools():
    from keysight_awg import configure_single_channel, load_and_play, generate_sine
    assert callable(configure_single_channel)

def test_version():
    import keysight_awg
    assert keysight_awg.__version__ == "0.1.0"
```

- [ ] **Step 2: Run the tests**

Run: `python -m pytest tests/test_top_level_api.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_top_level_api.py
git commit -m "test: add top-level API import tests"
```

---

### Task 4: Move scripts to `examples/` and clean up root

**Files:**
- Move: `multitone_demo.py` → `examples/multitone_demo.py`
- Move: `m8195a_stop.py` → `examples/stop_output.py`
- Move: `test_connection.py` → `examples/test_connection.py`
- Delete: `m8195a.py` (root copy — now lives in `src/`)
- Delete: `m8195a_tools.py` (root copy — now lives in `src/`)
- Delete: `multitone_generator.py` (root copy — now lives in `src/`)

**Interfaces:**
- Consumes: installed `keysight_awg` package (Tasks 1–2)
- Produces: runnable example scripts in `examples/` that use `from keysight_awg import ...`

- [ ] **Step 1: Create `examples/` directory**

```bash
mkdir -p examples
```

- [ ] **Step 2: Create `examples/multitone_demo.py`**

Copy `multitone_demo.py` to `examples/multitone_demo.py` and update the imports on lines 15–18 from:

```python
from m8195a import M8195A
from m8195a_tools import configure_single_channel, load_and_play
from multitone_generator import MultiToneGenerator, ToneSpec
from rigol_dho4204 import DHO4204
```

to:

```python
from keysight_awg import M8195A, configure_single_channel, load_and_play
from keysight_awg import MultiToneGenerator, ToneSpec
```

Remove the `from rigol_dho4204 import DHO4204` line (the Rigol code is commented out and the module doesn't exist in this project).

All other content remains identical.

- [ ] **Step 3: Create `examples/stop_output.py`**

Copy `m8195a_stop.py` to `examples/stop_output.py` and update the import on line 1 from:

```python
from m8195a import M8195A
```

to:

```python
from keysight_awg import M8195A
```

All other content remains identical.

- [ ] **Step 4: Create `examples/test_connection.py`**

Copy `test_connection.py` to `examples/test_connection.py` and update the import on line 7 from:

```python
from m8195a import M8195A
```

to:

```python
from keysight_awg import M8195A
```

All other content remains identical.

- [ ] **Step 5: Delete the original root-level source files**

```bash
rm m8195a.py m8195a_tools.py multitone_generator.py
rm multitone_demo.py m8195a_stop.py test_connection.py
```

- [ ] **Step 6: Clean up `__pycache__`**

```bash
rm -rf __pycache__
```

- [ ] **Step 7: Verify the package still works**

Run: `python -m pytest tests/ -v`
Expected: all tests PASS (the package is installed from `src/`, not the deleted root files).

- [ ] **Step 8: Verify an example script parses correctly**

Run: `python -c "import ast; ast.parse(open('examples/multitone_demo.py').read()); print('OK')"`
Expected: prints `OK` (confirms valid Python syntax and correct import rewriting).

- [ ] **Step 9: Commit**

```bash
git add examples/ tests/
git rm m8195a.py m8195a_tools.py multitone_generator.py multitone_demo.py m8195a_stop.py test_connection.py
git commit -m "refactor: move scripts to examples/, remove root-level source files"
```

---

### Task 5: Initialize git repo and make the first tagged release

**Files:**
- Modify: (git operations only, no file changes)

**Interfaces:**
- Consumes: all prior tasks
- Produces: a clean git repository with a `v0.1.0` tag

- [ ] **Step 1: Initialize git if not already a git repo**

```bash
git init
```

- [ ] **Step 2: Stage and commit everything**

If not already committed from prior tasks (i.e., this is the first git init):

```bash
git add .
git commit -m "feat: initial release of keysight_awg as a Python package

Wraps the M8195A AWG driver, high-level tools, and multitone
generator into an installable Python package using pyproject.toml
and src layout."
```

- [ ] **Step 3: Tag the release**

```bash
git tag -a v0.1.0 -m "v0.1.0 — initial package release"
```

- [ ] **Step 4: Final verification**

Run: `python -m pytest tests/ -v`
Expected: all tests PASS.

Run: `python -c "from keysight_awg import M8195A; print(M8195A.SCPI_PORT)"`
Expected: prints `5025`.

---

## Final Project Layout

```
keysight_awg/                     (project root)
├── .gitignore
├── pyproject.toml
├── src/
│   └── keysight_awg/
│       ├── __init__.py           # re-exports: M8195A, tools, multitone
│       ├── m8195a.py             # M8195A driver class
│       ├── tools.py              # configure_single_channel, load_and_play, generate_sine
│       └── multitone.py          # MultiToneGenerator, ToneSpec
├── examples/
│   ├── multitone_demo.py         # 3-tone demo with plotting + AWG playback
│   ├── stop_output.py            # quick stop-output script
│   └── test_connection.py        # connection test script
└── tests/
    ├── __init__.py
    ├── test_package.py           # metadata / version checks
    ├── test_imports.py           # module-level import checks
    └── test_top_level_api.py     # top-level API + basic MultiToneGenerator test
```

## Usage After Installation

```bash
pip install -e ".[dev]"       # editable install with test deps
pip install -e ".[plot]"      # editable install with matplotlib
pip install -e ".[dev,plot]"  # both
```

```python
from keysight_awg import M8195A, MultiToneGenerator, ToneSpec

with M8195A("192.168.1.10") as awg:
    # ...
```
