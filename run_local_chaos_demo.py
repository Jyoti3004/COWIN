"""Automated end-to-end chaos demo using local processes (no Docker/cloud).

Starts Zone A + Zone B + load balancer, runs a request stream, kills Zone A
mid-test, and reports whether the app stayed up. Great as a repeatable proof
for the report; the video/live demo should show the same on real infra.

Run:  python run_local_chaos_demo.py
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APP = os.path.join(ROOT, "member1-app-and-architecture", "app", "app.py")
LB = os.path.join(ROOT, "member2-cloud-infra", "local-sim", "lb.py")


def start(cmd, env_extra=None):
    env = dict(os.environ, **(env_extra or {}))
    return subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    py = sys.executable
    za = start([py, APP], {"ZONE": "ap-south-1a", "PORT": "9001"})
    zb = start([py, APP], {"ZONE": "ap-south-1b", "PORT": "9002"})
    lb = start([py, LB, "--listen", "8000", "--targets", "127.0.0.1:9001", "127.0.0.1:9002", "--interval", "1"])
    time.sleep(2)
    test = subprocess.Popen([py, os.path.join(HERE, "failover_test.py"),
                             "--url", "http://127.0.0.1:8000/health",
                             "--duration", "20", "--rate", "10"])
    time.sleep(8)
    print("\n>>> CHAOS: killing Zone A (ap-south-1a) now <<<\n", flush=True)
    za.kill()
    time.sleep(6)
    print("\n>>> RECOVERY: restarting Zone A <<<\n", flush=True)
    za = start([py, APP], {"ZONE": "ap-south-1a", "PORT": "9001"})
    test.wait()
    for p in (za, zb, lb):
        p.kill()


if __name__ == "__main__":
    main()
