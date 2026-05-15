[Unit]
Description=Hearth API (FastAPI / uvicorn)
# Start after the network is up so DATABASE_URL resolves
After=network.target
# If postgres is installed as a user service, depend on it here instead:
# After=postgresql.service

[Service]
Type=simple
WorkingDirectory={{APP_DIR}}/api

# Source the local env file if it exists (-prefix makes it optional)
EnvironmentFile=-{{APP_DIR}}/infra/local.env

ExecStart={{APP_DIR}}/api/.venv/bin/uvicorn life_dashboard.main:app \
    --host 127.0.0.1 \
    --port 1338 \
    --workers 2

# Restart on any non-zero exit; wait 10s to avoid tight crash loops
Restart=on-failure
RestartSec=10

# Capture stdout/stderr — view with: journalctl --user -u life-dashboard-api
StandardOutput=journal
StandardError=journal

[Install]
# default.target is the right target for user services (no root needed)
WantedBy=default.target
