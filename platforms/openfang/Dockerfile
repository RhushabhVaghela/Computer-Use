FROM ubuntu:22.04

# Avoid prompts during apt installs
ENV DEBIAN_FRONTEND=noninteractive

# Update and install dependencies
RUN apt-get update && apt-get install -y \
    xfce4 xfce4-goodies \
    tightvncserver \
    novnc websockify \
    python3 python3-pip python3-venv \
    curl wget git build-essential \
    dbus-x11 x11-xserver-utils \
    sudo xterm \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd -ms /bin/bash user \
    && echo "user:user" | chpasswd \
    && adduser user sudo \
    && echo "user ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

USER user
WORKDIR /home/user

# Setup VNC password
RUN mkdir -p /home/user/.vnc \
    && echo "password" | vncpasswd -f > /home/user/.vnc/passwd \
    && chmod 600 /home/user/.vnc/passwd

# Create xstartup script for VNC
RUN echo "#!/bin/bash\n\
    xrdb $HOME/.Xresources\n\
    startxfce4 &\n\
    " > /home/user/.vnc/xstartup \
    && chmod +x /home/user/.vnc/xstartup

# Configure dbus
RUN echo "export \$(dbus-launch)" >> /home/user/.bashrc

# Setup Python environment for Open-Interpreter
RUN python3 -m venv /home/user/venv
ENV PATH="/home/user/venv/bin:$PATH"

# Copy the Open-Interpreter init patch into the container
COPY --chown=user:user scripts/open_interpreter_init.patch /home/user/open_interpreter_init.patch

# Install Open-Interpreter, MCP SDK, and constraints safely
RUN mkdir -p /home/user/src-build/open-interpreter && \
    cd /home/user/src-build && \
    git clone https://github.com/OpenInterpreter/open-interpreter.git && \
    cd open-interpreter && \
    git apply /home/user/open_interpreter_init.patch || echo "Patch already applied or failed" && \
    pip install --no-cache-dir . mcp 'starlette<0.38.0,>=0.37.2' "open-interpreter[os]" && \
    cd /home/user && rm -rf /home/user/src-build

# Install OpenFang
# Using curl to download the install script, piped to bash
# Since we are running in arm64/amd64 docker, the binary should just work.
RUN curl -fsSL https://openfang.sh/install | sh
# Make sure OpenFang is in the path. The installer usually puts it in ~/.cargo/bin or ~/.local/bin
ENV PATH="/home/user/.local/bin:/home/user/.cargo/bin:$PATH"

# Copy the bridge scripts into the container
COPY --chown=user:user src/mcp_server.py /home/user/mcp_server.py
COPY --chown=user:user scripts/bridge.sh /home/user/bridge.sh

RUN chmod +x /home/user/bridge.sh

# Expose VNC (5901), NoVNC web access (8080), and OpenFang API (4200)
EXPOSE 5901 8080 4200

# Start VNC, NoVNC, and OpenFang
ENTRYPOINT ["/home/user/bridge.sh", "start"]
