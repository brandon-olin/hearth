<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!--
  Hearth — FastAPI backend LaunchAgent
  Auto-generated from this template by `service.sh install`.
  Installed to: ~/Library/LaunchAgents/com.lifedashboard.api.plist
-->
<plist version="1.0">
<dict>

  <!-- Unique label used by launchctl to identify this agent -->
  <key>Label</key>
  <string>com.lifedashboard.api</string>

  <!-- The wrapper script sources infra/local.env then exec's uvicorn -->
  <key>ProgramArguments</key>
  <array>
    <string>{{APP_DIR}}/infra/scripts/run-api.sh</string>
  </array>

  <!-- Run from the api/ directory so relative imports resolve correctly -->
  <key>WorkingDirectory</key>
  <string>{{APP_DIR}}/api</string>

  <!-- Start when this LaunchAgent is loaded (i.e. at login) -->
  <key>RunAtLoad</key>
  <true/>

  <!-- Restart automatically if the process exits unexpectedly -->
  <key>KeepAlive</key>
  <true/>

  <!-- Wait 10s before restarting to avoid tight crash-restart loops -->
  <key>ThrottleInterval</key>
  <integer>10</integer>

  <!-- Log files — directory is created by service.sh install if missing -->
  <key>StandardOutPath</key>
  <string>{{LOG_DIR}}/api.log</string>
  <key>StandardErrorPath</key>
  <string>{{LOG_DIR}}/api.error.log</string>

</dict>
</plist>
