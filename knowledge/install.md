# Installing CrabCakes

This guide walks you through installing CrabCakes, verifying that all dependencies are present, and fixing common install errors.

**Audience:** First-time users on a fresh system. If CrabCakes is already running, you can skip this file.

---

## Quick Start

If you have a modern Linux system with Python 3.11+ and GTK4 already installed:

```bash
git clone https://github.com/qsmtco/crabcakes.git
cd crabcakes
pip install -e .
crabcakes
```

That's it. The first launch creates `~/.config/crabcakes/` and walks you through provider configuration.

---

## Requirements

### Required

| Dependency | Minimum version | Why |
|---|---|---|
| **Python** | 3.11+ | Required by `pyproject.toml`. Earlier versions lack `tomllib` and other stdlib features. |
| **GTK 4** | 4.0+ | The UI is built on GTK4 via PyGObject. GTK3 will not work. |
| **PyGObject** | 3.48+ | Python bindings for GObject/GTK. Installed automatically by `pip install -e .`. |
| **WebSockets** | 12.0+ | For gateway communication. Installed automatically. |
| **Cryptography** | 41.0+ | For Ed25519 device authentication. Installed automatically. |
| **GitPython** | 3.1+ | For the review layer's git operations. Installed automatically. |

### Optional (recommended)

| Tool | Why |
|---|---|
| **xvfb** | Required to run CrabCakes in headless environments (CI, Docker). Install with `apt install xvfb` on Debian/Ubuntu. |
| **Ollama** | Local LLM runtime. Lets you run CrabCakes without a paid API key. See `providers.md` for setup. |
| **ripgrep** | Faster `search_files` tool. `apt install ripgrep` on Debian/Ubuntu. |

---

## Platform-Specific Instructions

### Linux (Debian / Ubuntu)

```bash
# System dependencies for GTK4 + PyGObject
sudo apt update
sudo apt install -y \
    python3 python3-pip python3-venv \
    libgirepository1.0-dev libgtk-4-1 libgtk-4-dev \
    gir1.2-gtk-4.0 gobject-introspection \
    libgirepository-2.0-0

# Then install CrabCakes
git clone https://github.com/qsmtco/crabcakes.git
cd crabcakes
pip install --user -e .
~/.local/bin/crabcakes
```

**Note:** Debian 12 (Bookworm) and Ubuntu 22.04+ ship GTK 4 in the default repos. Older releases need a backport.

### Linux (Fedora)

```bash
sudo dnf install -y \
    python3 python3-pip python3-devel \
    gtk4 gtk4-devel \
    gobject-introspection-devel \
    python3-gobject

git clone https://github.com/qsmtco/crabcakes.git
cd crabcakes
pip install --user -e .
~/.local/bin/crabcakes
```

### Linux (Arch)

```bash
sudo pacman -S --needed \
    python python-pip \
    gtk4 gobject-introspection \
    python-gobject

git clone https://github.com/qsmtco/crabcakes.git
cd crabcakes
pip install --user -e .
~/.local/bin/crabcakes
```

### macOS (Homebrew)

```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# System dependencies
brew install \
    python@3.12 \
    gtk4 \
    pygobject3 \
    pkg-config \
    gobject-introspection

# Then install CrabCakes
git clone https://github.com/qsmtco/crabcakes.git
cd crabcakes
pip3 install --user -e .
~/.local/bin/crabcakes
```

**Note:** On Apple Silicon Macs, ensure Homebrew is installed for `arm64` (the default). `brew --prefix` should return `/opt/homebrew`, not `/usr/local`.

### Windows

Windows support is **experimental**. The recommended approach is WSL2:

```powershell
# In PowerShell (admin)
wsl --install
# Restart, then in WSL Ubuntu:
sudo apt update
sudo apt install -y python3 python3-pip libgirepository1.0-dev libgtk-4-1
git clone https://github.com/qsmtco/crabcakes.git
cd crabcakes
pip install -e .
crabcakes
```

**Native Windows install is not officially supported.** If you need it, you can try MSYS2 + the GTK4 runtime, but expect rough edges.

---

## Verifying the Install

After installation, run these checks to confirm everything works:

### 1. Python and dependencies

```bash
python3 --version          # should be 3.11 or higher
python3 -c "import gi; gi.require_version('Gtk', '4.0'); from gi.repository import Gtk; print('GTK OK', Gtk.MAJOR_VERSION, Gtk.MINOR_VERSION)"
```

Expected output: `GTK OK 4 <minor>` (e.g., `GTK OK 4 12`).

### 2. CrabCakes imports

```bash
python3 -c "from ui.window import MainWindow; print('Import OK')"
```

Expected: `Import OK` with no errors. (No GUI launches — it only imports the module.)

### 3. Launch the app

```bash
crabcakes
```

Expected: The CrabCakes window opens with the Auxilium 🦀 tab visible. If you see a "no provider configured" dialog, that's the **first-run wizard** — see `providers.md` to complete setup.

### 4. Run from source (developer mode)

```bash
cd /path/to/crabcakes
python3 main.py
```

This bypasses the `crabcakes` entry point and runs `main.py` directly. Useful when iterating on the code.

### Headless verification (no display)

```bash
xvfb-run -a python3 -c "from ui.window import MainWindow; MainWindow(application=None); print('GUI constructs OK')"
```

If this works, CrabCakes is installable on headless systems (servers, CI).

---

## Common Install Errors

### `ModuleNotFoundError: No module named 'gi'`

**Cause:** PyGObject is not installed or the system `libgirepository` is missing.

**Fix (Debian/Ubuntu):**
```bash
sudo apt install libgirepository1.0-dev python3-gi gobject-introspection
pip install --user --break-system-packages pygobject
```

**Fix (Fedora):**
```bash
sudo dnf install python3-gobject gobject-introspection-devel
```

**Fix (macOS):**
```bash
brew install pygobject3 gobject-introspection pkg-config
pip install --user pygobject
```

### `Gtk-CRITICAL **: cannot open display`

**Cause:** No X11 or Wayland display available.

**Fix:** If you're on a headless server, run with Xvfb:
```bash
xvfb-run -a crabcakes
```

**Fix (Wayland):** If you're on Wayland and getting this error, your session may have fallen back to XWayland. Check:
```bash
echo $XDG_SESSION_TYPE   # should be "wayland" or "x11"
echo $WAYLAND_DISPLAY    # should be "wayland-0" or similar
```

If `$WAYLAND_DISPLAY` is empty, your desktop session isn't using Wayland. Log out and select a Wayland session at the login screen.

### `externally-managed-environment` (PEP 668)

**Cause:** Modern Debian/Ubuntu and Fedora mark the system Python as "externally managed," preventing `pip install` from modifying it.

**Fix (recommended):** Use a virtual environment:
```bash
python3 -m venv ~/.crabcakes-venv
source ~/.crabcakes-venv/bin/activate
pip install -e /path/to/crabcakes
crabcakes
```

**Fix (quick but not recommended):** Override the protection:
```bash
pip install --user --break-system-packages -e .
```

### `ImportError: libgtk-4.so.1: cannot open shared object file`

**Cause:** GTK 4 runtime libraries are not installed.

**Fix (Debian/Ubuntu):**
```bash
sudo apt install libgtk-4-1 libgtk-4-common
```

**Fix (Fedora):**
```bash
sudo dnf install gtk4
```

**Fix (macOS):**
```bash
brew install gtk4
```

After installing, you may need to refresh the linker cache:
```bash
sudo ldconfig   # Linux only
```

### PyGObject introspection cache errors

**Cause:** Stale or missing GObject introspection typelib cache.

**Fix:**
```bash
# Clear the cache and let it rebuild
rm -rf ~/.cache/g-ir-*
sudo ldconfig   # Linux only
```

If the error persists after this, file an issue with the full error output.

### `crabcakes: command not found`

**Cause:** The `crabcakes` script is installed to `~/.local/bin` but that directory is not on your `$PATH`.

**Fix:** Add this line to your `~/.bashrc`, `~/.zshrc`, or equivalent:
```bash
export PATH="$HOME/.local/bin:$PATH"
```

Then restart your shell or `source ~/.bashrc`.

**Alternative:** Use the Python module invocation:
```bash
python3 -m crabcakes
# or, from the source directory:
python3 main.py
```

### `Cannot find GDK-Backend` or display backend errors

**Cause:** No display backend available (X11 or Wayland).

**Fix:** On headless systems:
```bash
xvfb-run -a crabcakes
```

On a desktop with broken Wayland, try forcing X11:
```bash
GDK_BACKEND=x11 crabcakes
```

---

## Running in a Virtual Environment (Recommended)

A venv isolates CrabCakes and its dependencies from your system Python. This avoids the `externally-managed-environment` error and makes cleanup easy.

### Setup

```bash
# Create the venv (one-time)
python3 -m venv ~/crabcakes-venv

# Activate it (every shell session)
source ~/crabcakes-venv/bin/activate

# Install CrabCakes
pip install -e /path/to/crabcakes

# Run
crabcakes
```

### Auto-activation (optional)

Add to your `~/.bashrc`:
```bash
alias crabcakes='~/crabcakes-venv/bin/crabcakes'
```

Then `crabcakes` works from any directory without activating the venv.

### Cleanup

To uninstall:
```bash
# Delete the venv
rm -rf ~/crabcakes-venv

# Delete user config (optional, but resets to fresh install)
rm -rf ~/.config/crabcakes
```

---

## Installing for Development

If you want to contribute or modify CrabCakes:

```bash
git clone https://github.com/qsmtco/crabcakes.git
cd crabcakes

# Create a venv
python3 -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run the app
python3 main.py
```

### Dev dependencies

The `[dev]` extra includes:
- `pytest>=8.0` — test runner
- `ruff>=0.4` — linter

For KB indexing work (Auxilium Tier 1+), also install:
```bash
pip install sentence-transformers numpy
```

This adds ~700MB (mostly the PyTorch backend). Only needed if you're modifying `knowledge/` files and need to rebuild the embedding index.

---

## First Launch

When you run `crabcakes` for the first time:

1. The app creates `~/.config/crabcakes/` with default configs
2. The Auxilium 🦀 tab opens automatically
3. The first-run wizard appears (no LLM configured yet)
4. The wizard walks you through: install check → gateway check → provider picker
5. After completing the wizard, Auxilium is ready to use

See `providers.md` for the provider configuration step.

---

## Verifying a Working Install

After install + first launch, you should be able to:

- [x] The window opens without errors
- [x] The Auxilium 🦀 tab is visible
- [x] The first-run wizard appears (or, if already configured, the chat input is ready)
- [x] You can complete the wizard and configure a provider
- [x] Auxilium responds to a test message (after provider is configured)

If any of these fail, see the **Common Install Errors** section above, then `troubleshooting.md` for deeper debugging.

---

## When to Ask for Help

If the install doesn't work after trying the relevant fixes above:

1. Run `crabcakes --debug` (if available) or set `CRABCAKES_DEBUG=1` to get verbose logs
2. Check the `troubleshooting.md` file for known issues
3. Search existing issues: https://github.com/qsmtco/crabcakes/issues
4. File a new issue with: OS + version, Python version, GTK version, full error output
