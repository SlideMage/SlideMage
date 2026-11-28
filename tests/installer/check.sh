#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Runs inside one test container (tests/installer/run.py starts it): installs SlideMage with
# packaging/install-slidemage.sh and checks the result. /in holds the script and, for --from-zip, the release zip.
# Each check prints "CHECK <name> ok|FAILED <detail>"; "RESULT <key> <value>" lines are the numbers run.py records.
#
#   check.sh zip      install /in/SlideMage-linux-folder.zip (--from-zip, --unsigned unless a .sig is beside it)
#   check.sh release  install the latest release from GitHub (download and signature check)
set -uo pipefail
MODE="${1:-zip}"
SCRIPT=/in/install-slidemage.sh
APP="$HOME/.local/share/SlideMage"
FAILED=0

check() {   # check NAME OK? DETAIL
  if [ "$2" = 0 ]; then echo "CHECK $1 ok"; else echo "CHECK $1 FAILED $3"; FAILED=1; fi
}

if [ "$MODE" = zip ]; then
  ARGS=(--yes --from-zip /in/SlideMage-linux-folder.zip)
  [ -f /in/SlideMage-linux-folder.zip.sig ] || ARGS+=(--unsigned)
else
  ARGS=(--yes)
fi

# 1. Install, from nothing.
start=$(date +%s)
bash "$SCRIPT" "${ARGS[@]}" 2>&1 | tee /tmp/install.log
status=${PIPESTATUS[0]}
echo "RESULT install_seconds $(( $(date +%s) - start ))"
check install "$status" "exit $status"
grep -o "Need to get [0-9.,]* [kMG]B" /tmp/install.log | head -1 | sed 's/^/RESULT download /'
grep -E "^Total download size|^Total size of inbound packages" /tmp/install.log | head -1 | sed 's/^/RESULT download /'
echo "RESULT packages $(sed -n '/^System packages to install/{n;p}' /tmp/install.log | tr -s ' ')"
grep -q "compile self-test: ok" /tmp/install.log
check compile_self_test $? "no 'compile self-test: ok' in the installer's output"

# 2. Libraries: every shared object of the app resolves (Qt's optional plugins are listed, but only the ones the
#    window needs fail the check). With _internal/ on the search path, as the app has it at run time: PyInstaller
#    bundles some libraries under the build machine's names (Ubuntu's libbz2.so.1.0, which Fedora calls libbz2.so.1).
export LD_LIBRARY_PATH="$APP/_internal"
missing=$(find "$APP" -name '*.so*' -type f -exec ldd {} \; 2>/dev/null | grep "not found" | sort -u)
echo "RESULT ldd_missing $(echo "$missing" | awk '{print $1}' | sort -u | tr '\n' ' ')"
essential=$(for so in $(find "$APP" \( -name 'libqxcb.so' -o -name 'libQt6WebEngineCore.so*' -o -name 'libQt6Gui.so*' \
                          -o -name 'libQt6XcbQpa.so*' -o -name 'QtWebEngineProcess' \) -type f); do
              ldd "$so" 2>/dev/null | grep "not found"; done | sort -u)
unset LD_LIBRARY_PATH
check libraries "$([ -z "$essential" ]; echo $?)" "$essential"

# 3. The window under a virtual X server for 20 seconds: no missing library or platform plugin in its output. The
#    test tools are installed only now, so they cannot stand in for a library the installer forgot.
if command -v apt-get >/dev/null; then
  sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends xvfb xauth desktop-file-utils >/dev/null 2>&1
else
  sudo dnf install -y -q xorg-x11-server-Xvfb xorg-x11-xauth desktop-file-utils >/dev/null 2>&1
fi
desktop-file-validate "$HOME/.local/share/applications/slidemage.desktop" > /tmp/desktop.log 2>&1
check desktop_entry $? "$(cat /tmp/desktop.log)"
# QtWebEngine's Chromium sandbox needs privileges a container does not have; not a problem on a desktop.
QTWEBENGINE_DISABLE_SANDBOX=1 timeout 20 xvfb-run -a "$HOME/.local/bin/slidemage" > /tmp/window.log 2>&1
status=$?
problems=$(grep -iE "cannot open shared object|could not load the qt platform plugin|undefined symbol|Traceback" /tmp/window.log)
check window "$([ "$status" = 124 ] && [ -z "$problems" ]; echo $?)" "exit $status: $problems $(tail -5 /tmp/window.log)"

# 4. Again: a repair finds nothing to install and leaves a working installation.
bash "$SCRIPT" "${ARGS[@]}" --no-self-test > /tmp/again.log 2>&1
status=$?
check again "$status" "exit $status: $(tail -5 /tmp/again.log)"
grep -q "No system packages are missing" /tmp/again.log
check again_nothing_missing $? "$(grep -A2 '^System packages' /tmp/again.log)"
QT_QPA_PLATFORM=offscreen "$APP/SlideMage" --self-test > /dev/null 2>&1
check again_self_test $? "SlideMage --self-test failed after the second run"

# 5. Uninstall leaves nothing of SlideMage behind.
bash "$SCRIPT" --uninstall --yes > /tmp/uninstall.log 2>&1
check uninstall $? "$(tail -3 /tmp/uninstall.log)"
left=$(ls -d "$APP"* "$HOME/.local/bin/slidemage" "$HOME/.local/share/applications/slidemage.desktop" 2>/dev/null)
check uninstall_clean "$([ -z "$left" ]; echo $?)" "left: $left"

echo "RESULT failed $FAILED"
exit "$FAILED"
