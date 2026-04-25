#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "============================================================"
echo "  Open Interpreter Computer-Use MCP Server - Setup"
echo "============================================================"
echo ""

# Step 1: Virtual environment
if [ ! -d ".venv" ]; then
    echo "[1/4] Creating virtual environment..."
    python3 -m venv .venv
else
    echo "[1/4] Virtual environment already exists."
fi

source .venv/bin/activate

# Step 2: Install dependencies
echo "[2/4] Installing dependencies..."
pip install -r requirements.txt -q

# Step 3: Relax Open Interpreter constraints
OI_PATH="${OI_PATH:-$HOME/open-interpreter}"
if [ -f ".env" ]; then
    # Prioritize OI_PATH_LINUX, then OI_PATH
    VAL=$(grep "^OI_PATH_LINUX=" .env | cut -d'=' -f2- | tr -d '"' | tr -d "'")
    if [ -z "$VAL" ]; then
        VAL=$(grep "^OI_PATH=" .env | cut -d'=' -f2- | tr -d '"' | tr -d "'")
    fi
    if [ -n "$VAL" ]; then
        OI_PATH="$VAL"
    fi
fi

echo ""
echo "[3/4] Relaxing Python version constraints in pyproject.toml..."
echo "       Target: $OI_PATH"

if [ ! -d "$OI_PATH" ]; then
    echo "ERROR: Open Interpreter not found at $OI_PATH"
    echo "Set OI_PATH in your .env file."
    exit 1
fi

PYPROJECT="$OI_PATH/pyproject.toml"
if [ -f "$PYPROJECT" ]; then
    sed -i.bak 's/python = ">=3.9,<3.13"/python = ">=3.9"/' "$PYPROJECT"
    sed -i.bak 's/tiktoken = "\^0.7.0"/tiktoken = ">=0.8.0"/' "$PYPROJECT"
    sed -i.bak 's/starlette = "\^0.37.2"/starlette = ">=0.37.2"/' "$PYPROJECT" && rm -f "$PYPROJECT.bak"
    echo "       Done."
fi

# Step 4: Install Open Interpreter
echo ""
echo "[4/5] Installing Open Interpreter core dependencies..."
pip install setuptools poetry-core -q

if ! pip install -e "$OI_PATH[os]" -q; then
    echo ""
    echo "ERROR: Failed to install Open Interpreter dependencies."
    exit 1
fi

echo "       Open Interpreter installed successfully."

# Step 5: Install Playwright
echo ""
echo "[5/5] Installing Playwright browsers for DOM analysis..."
if ! playwright install chromium; then
    echo "WARNING: Playwright installation failed. Browser DOM tools may not work."
fi

echo ""
echo "============================================================"
echo "  Setup complete! Start the server with:"
echo ""
echo "    ./scripts/start.sh --stdio"
echo ""
echo "  New Features:"
echo "    - Coordinate accuracy fixed (DPI alignment)"
echo "    - Hierarchical UI Tree (read_screen_ui)"
echo "    - Browser-use DOM integration (browser_use_dom)"
echo ""
echo "  Browser Integration:"
echo "    Agent can launch browsers correctly via 'browser_action'."
echo "    To use already open browser, restart it with:"
echo "       chrome --remote-debugging-port=9222"
echo "============================================================"
