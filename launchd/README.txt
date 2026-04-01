Git autosave every 30 minutes (macOS launchd)
============================================

1. Edit com.construction-ai.git-autosave.plist if your project is not at:
   /Users/rodrigo/construction-ai
   (update both path strings in ProgramArguments.)

2. Copy the plist into LaunchAgents and load it:
   cp launchd/com.construction-ai.git-autosave.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.construction-ai.git-autosave.plist

   On newer macOS, if load fails, try:
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.construction-ai.git-autosave.plist

3. Stop later:
   launchctl unload ~/Library/LaunchAgents/com.construction-ai.git-autosave.plist
   # or: launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.construction-ai.git-autosave.plist

Logs: /tmp/construction-ai-git-autosave.out.log and .err.log

Commit-only (no push): set in plist under EnvironmentVariables:
  GIT_AUTOSAVE_NO_PUSH = 1

Or run once manually:
  bash scripts/git_autosave.sh
