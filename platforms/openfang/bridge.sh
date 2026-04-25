#!/bin/bash
# scripts/bridge.sh
# Unifies Docker start and Open-Interpreter run logic

COMMAND=$1

case "$COMMAND" in
    start)
        echo "Starting VNC Server..."
        rm -f /tmp/.X99-lock /tmp/.X1-lock
        vncserver :1 -geometry 1280x720 -depth 24
        export DISPLAY=:1

        echo "Starting NoVNC WebSocket Server on port 8080..."
        /usr/share/novnc/utils/launch.sh --vnc localhost:5901 --listen 8080 &

        echo "Starting OpenFang daemon..."
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

        # Dynamically inject MCP configuration if missing
        CONFIG_DIR="$HOME/.config/openfang"
        CONFIG_FILE="$CONFIG_DIR/config.toml"
        mkdir -p "$CONFIG_DIR"
        
        # Verify if open-interpreter is already in config
        if ! grep -q "name = \"open_interpreter\"" "$CONFIG_FILE" 2>/dev/null; then
            echo -e "\n# --- Auto-injected by OpenFang-Interpreter-Bridge ---" >> "$CONFIG_FILE"
            echo "[[mcp_servers]]" >> "$CONFIG_FILE"
            echo "name = \"open_interpreter\"" >> "$CONFIG_FILE"
            echo "timeout_secs = 600" >> "$CONFIG_FILE"
            echo "" >> "$CONFIG_FILE"
            echo "[mcp_servers.transport]" >> "$CONFIG_FILE"
            echo "type = \"stdio\"" >> "$CONFIG_FILE"
            echo "command = \"/home/user/venv/bin/python\"" >> "$CONFIG_FILE"
            echo "args = [\"/home/user/mcp_server.py\"]" >> "$CONFIG_FILE"
            echo "# ----------------------------------------------------" >> "$CONFIG_FILE"
            echo "Open-Interpreter MCP server automatically injected into $CONFIG_FILE"
        fi

        openfang start &

        echo "Container is running! Connect to the GUI via http://localhost:8080/vnc.html"
        wait
        ;;
        
    run)
        source /home/user/venv/bin/activate
        export OPENAI_API_BASE="http://localhost:4200/v1"
        export OPENAI_API_KEY="openfang-local" 
        export DISPLAY=:1

        echo "Starting Open-Interpreter connected to OpenFang (http://localhost:4200/v1)"
        interpreter
        ;;
        
    hand)
        ACTION=$2
        shift 2 # move to the targets
        TARGETS=("$@")
        HANDS_DIR="$(cd "$(dirname "$0")/../hands" && pwd)"
        
        # Ensure hands dir exists
        mkdir -p "$HANDS_DIR"

        if [ "$ACTION" = "register" ]; then
            if [ ${#TARGETS[@]} -eq 0 ]; then
                echo "Please provide one or more directory paths to register. Example: ./bridge.sh hand register ./my-hand"
                exit 1
            fi
            
            for TARGET in "${TARGETS[@]}"; do
                if [ -d "$TARGET" ]; then
                    HAND_NAME=$(basename "$TARGET")
                    DEST="$HANDS_DIR/$HAND_NAME"
                    if [ -d "$DEST" ]; then
                        echo "Hand '$HAND_NAME' already exists. Overwriting..."
                        rm -rf "$DEST"
                    fi
                    cp -r "$TARGET" "$HANDS_DIR/"
                    echo "Successfully registered hand: $HAND_NAME"
                else
                    echo "Warning: '$TARGET' is not a valid directory."
                fi
            done
            
        elif [ "$ACTION" = "unregister" ]; then
            if [ ${#TARGETS[@]} -eq 0 ]; then
                echo "Please provide hand names or --all to unregister. Example: ./bridge.sh hand unregister my-hand"
                exit 1
            fi
            
            # Check for --all 
            ALL=false
            for TARGET in "${TARGETS[@]}"; do
                if [ "$TARGET" = "--all" ]; then
                    ALL=true
                    break
                fi
            done
            
            if [ "$ALL" = true ]; then
                echo "Unregistering ALL hands..."
                rm -rf "$HANDS_DIR"/*
                echo "All hands unregistered successfully."
            else
                for TARGET in "${TARGETS[@]}"; do
                    if [ "$TARGET" != "--all" ]; then
                        DEST="$HANDS_DIR/$TARGET"
                        if [ -d "$DEST" ]; then
                            rm -rf "$DEST"
                            echo "Successfully unregistered hand: $TARGET"
                        else
                            echo "Warning: Hand '$TARGET' not found."
                        fi
                    fi
                done
            fi
            
        else
            echo "Usage: $0 hand {register|unregister} [--all] [paths/names...]"
            exit 1
        fi
        ;;
        
    *)
        echo "Usage: $0 {start|run|hand}"
        exit 1
        ;;
esac
