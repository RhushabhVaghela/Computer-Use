#!/bin/bash

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# Activate venv
if [ ! -d ".venv" ]; then
    echo "[ERROR]: Virtual environment not found. Please run ./scripts/setup.sh first."
    exit 1
fi
source .venv/bin/activate

# Check for arguments
ARGS="$@"
if [ -z "$ARGS" ]; then
    echo "[INFO]: No transport specified, defaulting to stdio mode."
    ARGS="--stdio"
fi

# Check for hybrid flag
SERVER_SCRIPT="src/server.py"
if [[ "$ARGS" == *"--hybrid"* ]]; then
    SERVER_SCRIPT="src/hybrid_server.py"
    # Remove --hybrid from args
    ARGS="${ARGS/--hybrid/}"
fi

echo ""
echo "============================================================"
echo "  OI Computer-Use Server Launching"
echo "  Mode: $SERVER_SCRIPT"
echo "  Args: $ARGS"
echo "============================================================"
echo ""

python3 $SERVER_SCRIPT $ARGS
