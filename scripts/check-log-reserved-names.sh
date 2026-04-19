#!/usr/bin/env bash
# Block `extra={... "name": ..., ...}` calls that collide with
# stdlib `LogRecord`'s reserved attribute names. The logger raises
# `KeyError("Attempt to overwrite …")` at runtime if any of these keys
# are passed via `extra=`.
#
# Reserved keys: name, msg, args, levelname, levelno, pathname,
# filename, module, exc_info, exc_text, stack_info, lineno, funcName,
# created, msecs, relativeCreated, thread, threadName, processName,
# process, message, asctime.

set -euo pipefail

reserved='"(name|msg|args|levelname|levelno|pathname|filename|module|exc_info|exc_text|stack_info|lineno|funcName|created|msecs|relativeCreated|thread|threadName|processName|process|message|asctime)"'

matches=$(grep -rEn "extra=\{[^}]*${reserved}\s*:" termiclaw/ 2>/dev/null || true)

if [ -n "$matches" ]; then
    echo "ERROR: 'extra=' dict uses a reserved LogRecord attribute key."
    echo "Rename the key (e.g., 'name' -> 'container_name')."
    echo
    echo "$matches"
    exit 1
fi
