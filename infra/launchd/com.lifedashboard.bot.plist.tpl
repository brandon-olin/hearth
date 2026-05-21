<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!--
  Hearth — Telegram bot LaunchAgent
  Auto-generated from this template by `make bot-install`.
  Installed to: ~/Library/LaunchAgents/com.lifedashboard.bot.plist
-->
<plist version="1.0">
<dict>

  <key>Label</key>
  <string>com.lifedashboard.bot</string>

  <key>ProgramArguments</key>
  <array>
    <string>{{APP_DIR}}/infra/scripts/run-bot.sh</string>
  </array>

  <key>WorkingDirectory</key>
  <string>{{APP_DIR}}</string>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <!-- Wait 30s before restarting — avoids hammering Telegram API on auth errors -->
  <key>ThrottleInterval</key>
  <integer>30</integer>

  <key>StandardOutPath</key>
  <string>{{LOG_DIR}}/bot.log</string>
  <key>StandardErrorPath</key>
  <string>{{LOG_DIR}}/bot.error.log</string>

</dict>
</plist>
