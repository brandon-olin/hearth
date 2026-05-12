<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.lifedashboard.postgres</string>

    <key>ProgramArguments</key>
    <array>
        <string>{{PG_BIN_DIR}}/postgres</string>
        <string>-D</string>
        <string>{{PG_DATA_DIR}}</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>ThrottleInterval</key>
    <integer>10</integer>

    <key>StandardOutPath</key>
    <string>{{LOG_DIR}}/postgres.log</string>

    <key>StandardErrorPath</key>
    <string>{{LOG_DIR}}/postgres.error.log</string>

    <key>WorkingDirectory</key>
    <string>{{APP_DIR}}</string>
</dict>
</plist>
