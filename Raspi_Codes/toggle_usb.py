#!/usr/bin/env python3
import subprocess
import sys
import time

USB2_HUB = "1-1"   # Raspberry Pi 4 USB 2.0 hub

def run(cmd):
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)

def all_off():
    # Turn off USB2 hub
    run(["sudo", "uhubctl", "-l", USB2_HUB, "-a", "off"])

    print("\nALL USB PORTS ARE NOW OFF\n")

def all_on():
    # Turn on USB2 hub
    run(["sudo", "uhubctl", "-l", USB2_HUB, "-a", "on"])

    print("\nALL USB PORTS ARE NOW ON\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 toggle_all_ports.py on|off")
        sys.exit(1)

    action = sys.argv[1].lower()

    if action == "on":
        all_on()
    elif action == "off":
        all_off()
    else:
        print("Unknown action:", action)
