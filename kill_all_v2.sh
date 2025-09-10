# 1) Kill any running scheduler/runner and its whole process group
for pid in $(pgrep -f 'times_daily_runner|run_times_epub|times_to_epub'); do
  pgid=$(ps -o pgid= -p "$pid" | tr -d ' ')
  [ -n "$pgid" ] && kill -TERM -- -"${pgid}"
done
sleep 2

# 2) Sweep typical leftovers (TERM, then KILL)
pkill -TERM -f 'times_to_epub.*\.py'      2>/dev/null
pkill -TERM -x chromedriver               2>/dev/null
pkill -TERM -f '/opt/google/chrome/chrome' 2>/dev/null
pkill -TERM -x Xvfb                       2>/dev/null
sleep 2
pkill -KILL -x chromedriver               2>/dev/null
pkill -KILL -f '/opt/google/chrome/chrome' 2>/dev/null
pkill -KILL -x Xvfb                       2>/dev/null

# 3) Remove any locked Chrome profile files (safe to delete)
rm -f ~/.cache/times_chrome_profile/Singleton* 2>/dev/null
