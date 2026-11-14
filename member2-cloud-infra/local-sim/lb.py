"""Tiny round-robin load balancer with active health checks (stdlib only).

Fallback for laptops without Docker. Mimics an AWS ALB:
  - round-robin across targets
  - background health check every 2 s marks targets healthy/unhealthy
  - on connection error, retries on the next healthy target

Usage:
  ZONE=ap-south-1a PORT=9001 python app.py &
  ZONE=ap-south-1b PORT=9002 python app.py &
  python lb.py --listen 8000 --targets 127.0.0.1:9001 127.0.0.1:9002
"""
import argparse
import itertools
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

targets = []          # list of "host:port"
healthy = {}          # target -> bool
lock = threading.Lock()
rr = itertools.count()


def health_loop(interval):
    while True:
        for t in targets:
            try:
                urllib.request.urlopen(f"http://{t}/health", timeout=1).read()
                ok = True
            except Exception:
                ok = False
            with lock:
                if healthy.get(t) != ok:
                    print(f"[LB] target {t} -> {'HEALTHY' if ok else 'UNHEALTHY'}", flush=True)
                healthy[t] = ok
        time.sleep(interval)


def pick_order():
    with lock:
        live = [t for t in targets if healthy.get(t)]
    if not live:
        return []
    start = next(rr) % len(live)
    return live[start:] + live[:start]


class LB(BaseHTTPRequestHandler):
    def do_GET(self):
        order = pick_order() or list(targets)   # if all down, still try
        for t in order:
            try:
                with urllib.request.urlopen(f"http://{t}{self.path}", timeout=2) as r:
                    body = r.read()
                    self.send_response(r.status)
                    self.send_header("Content-Type", r.headers.get("Content-Type", "application/json"))
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("X-Served-By-Zone", r.headers.get("X-Served-By-Zone", "?"))
                    self.end_headers()
                    self.wfile.write(body)
                    return
            except Exception:
                with lock:
                    healthy[t] = False      # passive detection: fail fast
                continue
        msg = b'{"error":"no healthy targets"}'
        self.send_response(503)
        self.send_header("Content-Length", str(len(msg)))
        self.end_headers()
        self.wfile.write(msg)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", type=int, default=8000)
    ap.add_argument("--targets", nargs="+", required=True)
    ap.add_argument("--interval", type=float, default=2.0)
    a = ap.parse_args()
    targets.extend(a.targets)
    for t in targets:
        healthy[t] = True
    threading.Thread(target=health_loop, args=(a.interval,), daemon=True).start()
    print(f"[LB] listening on :{a.listen}, targets={targets}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", a.listen), LB).serve_forever()
