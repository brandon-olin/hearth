[Unit]
Description=Hearth Web (Next.js)
# Wait for the API to be up before starting the web process
After=network.target life-dashboard-api.service

[Service]
Type=simple
WorkingDirectory={{APP_DIR}}/web

EnvironmentFile=-{{APP_DIR}}/infra/local.env

ExecStart={{APP_DIR}}/web/node_modules/.bin/next start \
    --hostname 127.0.0.1 \
    --port 1337

Restart=on-failure
RestartSec=10

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
