#!/bin/bash
# Install launchd job: daily report to Telegram at 09:00
set -e
PLIST=~/Library/LaunchAgents/com.commander-os.daily-report.plist
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.commander-os.daily-report</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-c</string>
    <string>cd $HOME/commander-os/backend &amp;&amp; unset PYTHONPATH &amp;&amp; source .venv/bin/activate &amp;&amp; python -m app.jobs.daily_report >> /tmp/commander_daily_report.log 2>&amp;1</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
</dict>
</plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "daily report scheduled 09:00 — $(launchctl list | grep commander-os || true)"
