[Unit]
Description=Life Dashboard PostgreSQL
After=network.target

[Service]
Type=simple
ExecStart={{PG_BIN_DIR}}/postgres -D "{{PG_DATA_DIR}}"
ExecStop={{PG_BIN_DIR}}/pg_ctl stop -D "{{PG_DATA_DIR}}" -m fast
Restart=on-failure
RestartSec=10

StandardOutput=journal
StandardError=journal
SyslogIdentifier=life-dashboard-postgres

[Install]
WantedBy=default.target
