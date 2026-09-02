# -*- coding: utf-8 -*-
import os, sys, subprocess

# Get Qobuz App ID and Secrets — Gist
# https://gist.github.com/vitiko98/bb89fd203d08e285d06abf40d96db592
title = "Qobuz App ID and Secrets"

# Try to import qobuz_dl, install if not found.
try:
    from qobuz_dl.bundle import Bundle
except ModuleNotFoundError:
    print("qobuz_dl not found, installing...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "qobuz_dl"])
    # Clear the console after installation.
    os.system('cls' if os.name == 'nt' else 'clear')
    # Try importing again after installation.
    from qobuz_dl.bundle import Bundle

bundle = Bundle()
appId = bundle.get_app_id()
entryPrefix = f"\n{' ' * 2}\u2014 "
secrets = entryPrefix + (entryPrefix.join(bundle.get_secrets().values()))

print(
    f"{chr(0x002A) * 5} {title} {chr(0x002A) * 5}\n\n"
    f"{(appIdLine := f'App ID: {appId}')}\n"
    f"{chr(0x203E) * len(appIdLine)}\n"
    f"App Secrets (the first usually works):{secrets}\n"
)

if os.name == 'nt':
    os.system(f'title {title}& pause')
else:
    os.system(f'printf "\33]0;{title}\a"; read -n1 -s -p "Press any key to exit..."')

sys.exit(0)
