#!/usr/bin/env bash
# rc.sh -- run a command and record ITS exit code before anything else can.
#
# ⛔⛔ WHY THIS EXISTS (ruling E+). Four times in one arc a quick checking
# loop reported a passing exit code that belonged to something else:
#   * `cmd | tail; echo $?`         -- $? was tail's
#   * `cmd | head; echo "rc=$?"`    -- $? was head's
#   * `printf "%s %s" "$(basename $g)" "$?"`
#                                   -- the command substitution ran FIRST and
#                                      reset $? to basename's 0
# The third shape is why `set -o pipefail` alone was not the fix: there is no
# pipe in it. Every "rc=0" those loops printed meant nothing, and one of them
# hid a gate that was really exiting 1.
#
# ⇒ Capture the code on the very next statement, in one place, and print it
#   with the command so a reader can see which status is which.
#
# USAGE:  . ci/rc.sh
#         run_rc        python model/gate_x.py        # output shown
#         run_rc_quiet  python model/gate_x.py        # output discarded
# Both print `rc=<n>  <command>` and RETURN that code, so `|| ...` still works.
# `model/gate_shell_rc.py` refuses a hand-written `$?` anywhere it could read
# the wrong status.

run_rc() {
  "$@"
  local rc=$?
  printf 'rc=%d  %s\n' "$rc" "$*"
  return "$rc"
}

run_rc_quiet() {
  "$@" > /dev/null 2>&1
  local rc=$?
  printf 'rc=%d  %s\n' "$rc" "$*"
  return "$rc"
}
