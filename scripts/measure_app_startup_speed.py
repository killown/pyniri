#!/usr/bin/env python3
import sys
import time
import shutil
import os
import signal
from pyniri import NiriSocket

if len(sys.argv) < 2:
    print(f"Usage: {sys.argv[0]} <app_command>")
    sys.exit(1)

app_cmd = sys.argv[1]

if not app_cmd.startswith(("/", "./", "../")):
    full_path = shutil.which(app_cmd)
    if full_path:
        app_cmd = full_path

sock = NiriSocket()

start_time = time.perf_counter()
sock.spawn(app_cmd)

for event in sock.watch():
    if "WindowOpenedOrChanged" in event:
        end_time = time.perf_counter()
        window = event["WindowOpenedOrChanged"]["window"]

        duration_ms = (end_time - start_time) * 1000
        print(f"Startup Time: {duration_ms:.2f} ms")

        pid = window.get("pid")
        if pid:
            os.kill(pid, signal.SIGTERM)
        break
