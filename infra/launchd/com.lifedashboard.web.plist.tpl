<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!--
  Life Dashboard — Next.js frontend LaunchAgent
  Auto-generated from this template by `service.sh install`.
  Installed to: ~/Library/LaunchAgents/com.lifedashboard.web.plist
-->
<plist version="1.0">
<dict>

  <key>Label</key>
  <string>com.lifedashboard.web</string>

  <!-- The wrapper script sources infra/local.env then exec's `next start` -->
  <key>ProgramArguments</key>
  <array>
    <string>{{APP_DIR}}/infra/scripts/run-web.sh</string>
  </array>

  <key>WorkingDirectory</key>
  <string>{{APP_DIR}}/web</string>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>ThrottleInterval</key>
  <integer>10</integer>

  <key>StandardOutPath</key>
  <string>{{LOG_DIR}}/web.log</string>
  <key>StandardErrorPath</key>
  <string>{{LOG_DIR}}/web.error.log</string>

</dict>
</plist>
