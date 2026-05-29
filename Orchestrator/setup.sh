#!/bin/bash
# setup.sh — sets up the Python environment for the Orchestrator project.
#
# Uses uv to download Python 3.11 and create an isolated .venv.
# Does not modify the system Python or any existing Python installation.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
REQ_FILE="$SCRIPT_DIR/requirements.txt"

echo
echo "══════════════════════════════════════"
echo "  Orchestrator — Setup"
echo "══════════════════════════════════════"
echo

# ── uv ───────────────────────────────────────────────────────────────────────
# uv manages Python and the venv. It downloads Python into its own cache —
# no changes to system Python or any other installed versions.
if command -v uv &>/dev/null; then
    UV="$(command -v uv)"
elif [[ -x "$HOME/.local/bin/uv" ]]; then
    UV="$HOME/.local/bin/uv"
else
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    UV="$HOME/.local/bin/uv"
fi
echo "✓  uv: $("$UV" --version)"

# ── Virtual environment ───────────────────────────────────────────────────────
if [[ -d "$VENV_DIR" ]]; then
    echo "✓  .venv already exists — keeping it"
else
    echo "Creating virtual environment with Python 3.11..."
    "$UV" venv --python 3.11 "$VENV_DIR"
    echo "✓  .venv created"
fi

# ── Packages ──────────────────────────────────────────────────────────────────
echo "Installing packages..."
# --reinstall-package setuptools ensures the version constraint in requirements.txt
# is always respected, even if a newer (incompatible) version is already present.
"$UV" pip install --python "$VENV_DIR" --reinstall-package setuptools -r "$REQ_FILE"
echo "✓  Packages installed"

# ── Done ──────────────────────────────────────────────────────────────────────
echo
echo "══════════════════════════════════════"
echo "  Setup complete."
echo "══════════════════════════════════════"
echo
echo "  Next steps:"
echo "  1. Install LM Studio: https://lmstudio.ai"
echo "  2. Download and load a main model (e.g. Qwen3.5-35b-a3b)"
echo "  3. For --security medium/high: also load mistralai/ministral-3-3b"
echo "  4. Start the LM Studio local server"
echo "  5. ./orchestrator --list-agents"
echo "  6. ./ReleaseNotes/release_pipeline --dry-run"
echo
echo "  See SETUP.md for full instructions."
echo
