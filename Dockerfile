FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ARG NB_UID=10001
ARG NB_GID=10001
ARG BUILD_WHATSAPP_BRIDGE=0

# Install Node.js 20 for the WhatsApp bridge
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg git && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get purge -y gnupg && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY pyproject.toml README.md LICENSE ./
RUN mkdir -p nanobot bridge && touch nanobot/__init__.py && \
    uv pip install --system --no-cache . && \
    rm -rf nanobot bridge

# Copy the full source and install
COPY nanobot/ nanobot/
COPY bridge/ bridge/
RUN uv pip install --system --no-cache .

# Build the WhatsApp bridge
WORKDIR /app/bridge
RUN if [ "${BUILD_WHATSAPP_BRIDGE}" = "1" ]; then \
      git config --global --add url."https://github.com/".insteadOf "ssh://git@github.com/" && \
      git config --global --add url."https://github.com/".insteadOf "ssh://git@github.com" && \
      git config --global --add url."https://github.com/".insteadOf "git@github.com:" && \
      npm install && npm run build; \
    else \
      echo "Skipping WhatsApp bridge build (BUILD_WHATSAPP_BRIDGE=${BUILD_WHATSAPP_BRIDGE})."; \
    fi
WORKDIR /app

# Create runtime home directory and run as non-root numeric UID/GID.
# This avoids collisions when host IDs (e.g. macOS GID 20) already exist in image.
RUN mkdir -p /home/nanobot/.nanobot && \
    chown -R ${NB_UID}:${NB_GID} /home/nanobot

ENV HOME=/home/nanobot
USER ${NB_UID}:${NB_GID}
WORKDIR /home/nanobot

# Gateway default port
EXPOSE 18790

ENTRYPOINT ["nanobot"]
CMD ["status"]
