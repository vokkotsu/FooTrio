import argparse
import atexit
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import quote, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")

procs = []
_cleanup_done = False


def cleanup():
    global _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True
    for p in procs:
        try:
            if p.poll() is None:
                p.terminate()
        except Exception:
            pass
    for p in procs:
        try:
            p.wait(timeout=5)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


atexit.register(cleanup)


def ensure_backend_deps():
    required = ("fastapi", "uvicorn")
    missing = [m for m in required if importlib.util.find_spec(m) is None]
    if not missing:
        return
    req_file = os.path.join(BACKEND, "requirements.txt")
    print(f"Installing backend dependencies ({', '.join(missing)} missing)...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])


def start_backend(port):
    env = os.environ.copy()
    env["PORT"] = str(port)
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
        "--proxy-headers",
        "--forwarded-allow-ips=*",
    ]
    p = subprocess.Popen(cmd, cwd=BACKEND, env=env)
    procs.append(p)
    return p


def wait_for_backend(port, timeout=20):
    url = f"http://127.0.0.1:{port}/"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def _stream_output(pipe, prefix, on_line=None, quiet=False):
    try:
        for raw in iter(pipe.readline, ""):
            line = raw.rstrip()
            if line and not quiet:
                print(f"[{prefix}] {line}")
            if on_line:
                on_line(line)
    except Exception:
        pass
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def start_tunnel(port, tunnel):
    tunnel = tunnel.lower()
    ngrok = shutil.which("ngrok")
    cloudflared = shutil.which("cloudflared")
    ssh = shutil.which("ssh")

    if tunnel == "auto":
        if cloudflared:
            tunnel = "cloudflared"
        elif ngrok:
            tunnel = "ngrok"
        elif ssh:
            tunnel = "ssh"
        else:
            tunnel = "none"

    if tunnel == "ngrok":
        if not ngrok:
            print("ngrok not found. Install it from https://ngrok.com/download")
            return None, "none"
        cmd = [ngrok, "http", str(port), "--log", "stdout"]
    elif tunnel == "cloudflared":
        if not cloudflared:
            print("cloudflared not found. Install it from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/")
            return None, "none"
        cmd = [
            cloudflared,
            "tunnel",
            "--no-autoupdate",
            "--protocol",
            "http2",
            "--url",
            f"http://127.0.0.1:{port}",
        ]
    elif tunnel == "ssh":
        if not ssh:
            print("ssh not found.")
            return None, "none"
        null_known_hosts = "NUL" if os.name == "nt" else "/dev/null"
        cmd = [
            ssh,
            "-tt",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            f"UserKnownHostsFile={null_known_hosts}",
            "-o",
            "ServerAliveInterval=30",
            "-R",
            f"80:localhost:{port}",
            "nokey@localhost.run",
        ]
    else:
        return None, "none"

    try:
        p = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception as e:
        print(f"Failed to start tunnel ({tunnel}): {e}")
        return None, "none"
    procs.append(p)
    return p, tunnel


def extract_public_url(line):
    # cloudflared / ngrok / localhost.run (lhr.life) / serveo style URLs
    m = re.search(
        r"https://[a-zA-Z0-9.-]+\.(?:trycloudflare\.com|ngrok-free\.app|ngrok\.app|ngrok\.io|lhr\.life|localhost\.run)",
        line,
    )
    if m:
        return m.group(0)
    m = re.search(r"https://[^\s\"'<>]+", line)
    if m:
        url = m.group(0).rstrip(".,)")
        host = (urlparse(url).hostname or "").lower()
        if (
            host.endswith("trycloudflare.com")
            or "ngrok" in host
            or host.endswith("lhr.life")
            or host.endswith("localhost.run")
        ):
            return url
    return None


def get_ngrok_url_from_api(timeout=20):
    api = "http://127.0.0.1:4040/api/tunnels"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(api, timeout=1) as resp:
                data = json.loads(resp.read().decode("utf-8", "ignore"))
            for t in data.get("tunnels", []):
                pub = t.get("public_url", "")
                if pub.startswith("https://"):
                    return pub
            tunnels = data.get("tunnels", [])
            if tunnels:
                return tunnels[0].get("public_url")
        except Exception:
            time.sleep(0.5)
    return None


def to_ws_url(http_url):
    if http_url.startswith("https://"):
        return "wss://" + http_url[len("https://") :] + "/ws"
    if http_url.startswith("http://"):
        return "ws://" + http_url[len("http://") :] + "/ws"
    return http_url.rstrip("/") + "/ws"


def print_ready(http_url, ws_url, vercel_url):
    vercel_url = (vercel_url or "https://footrio-pavo2.vercel.app").strip().rstrip("/")
    sep = "&" if "?" in vercel_url else "?"
    play_url = f"{vercel_url}{sep}ws={quote(ws_url, safe='')}"

    print()
    print("=" * 60)
    print("Backend is running and exposed via a public tunnel.")
    print()
    print("Open this URL to play (do not open the tunnel URL directly):")
    print(f"  {play_url}")
    print()
    print(f"Game URL     : {vercel_url}/")
    print(f"WebSocket    : {ws_url}")
    print()
    print("Keep this terminal open while playing. Press Ctrl+C to stop.")
    print("=" * 60)
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Start the FooTrio backend locally and expose it so the Vercel game can connect."
    )
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)), help="Local backend port (default: 8000)")
    parser.add_argument(
        "--tunnel",
        choices=["auto", "cloudflared", "ngrok", "ssh", "none"],
        default="auto",
        help="Public tunnel type (default: auto; try available cloudflared/ngrok/ssh)",
    )
    parser.add_argument(
        "--vercel-url",
        default=os.environ.get("VERCEL_URL", "https://footrio-pavo2.vercel.app"),
        help="Vercel app URL to open (default: https://footrio-pavo2.vercel.app)",
    )
    args = parser.parse_args()

    try:
        ensure_backend_deps()
    except subprocess.CalledProcessError as e:
        print(f"Dependency installation failed (exit code {e.returncode}).")
        print("Install manually: cd backend && pip install -r requirements.txt")
        sys.exit(e.returncode or 1)
    except FileNotFoundError as e:
        print(f"Required tool not found: {e.filename or e}")
        sys.exit(1)

    backend_proc = start_backend(args.port)
    print(f"Starting backend (port {args.port}) for the Vercel game...")

    if not wait_for_backend(args.port):
        print("Backend failed to start within 20 seconds. Check the output above for errors.")
        cleanup()
        sys.exit(1)
    print("Backend is ready. Opening a public tunnel so Vercel can connect...")

    tunnel_proc, tunnel_kind = start_tunnel(args.port, args.tunnel)

    announced = {"done": False}

    def announce(http_url):
        if not http_url or announced["done"]:
            return
        announced["done"] = True
        ws_url = to_ws_url(http_url)
        vercel_url = (args.vercel_url or "").strip().rstrip("/")
        print_ready(http_url, ws_url, vercel_url)

    if tunnel_proc and tunnel_proc.stdout:
        def on_line(line):
            url = extract_public_url(line)
            if url:
                announce(url)

        threading.Thread(
            target=_stream_output,
            args=(tunnel_proc.stdout, tunnel_kind, on_line),
            kwargs={"quiet": True},
            daemon=True,
        ).start()

    if tunnel_kind == "ngrok" and not announced["done"]:
        url = get_ngrok_url_from_api()
        if url:
            announce(url)

    if tunnel_kind == "none" or not tunnel_proc:
        print()
        print("Error: no public tunnel available. The Vercel game cannot connect without a public URL.")
        print("Install a tunnel tool and run again (just: python app.py):")
        print("  - cloudflared (recommended, no account): https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/")
        print("  - ngrok                               : https://ngrok.com/download")
        print("  - or ensure 'ssh' is available (fallback to localhost.run)")
        cleanup()
        sys.exit(1)

    def handle_sigint(sig, frame):
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGINT, handle_sigint)
    except Exception:
        pass

    try:
        while True:
            if backend_proc.poll() is not None:
                print(f"\nBackend exited (code {backend_proc.returncode}). Stopping...")
                return
            if tunnel_proc and tunnel_proc.poll() is not None:
                if not announced["done"]:
                    print(f"\nTunnel exited (code {tunnel_proc.returncode}) before a public URL was obtained.")
                    print("Cannot connect the Vercel game without a public URL. Try running again with --tunnel cloudflared or --tunnel ngrok.")
                    cleanup()
                    return
                print(f"\nTunnel disconnected (code {tunnel_proc.returncode}). Attempting to open a new tunnel...")
                announced["done"] = False
                tunnel_proc, tunnel_kind = start_tunnel(args.port, args.tunnel)
                if not tunnel_proc or tunnel_kind == "none":
                    print("Failed to reopen the tunnel. Stop and run 'python app.py' again.")
                    cleanup()
                    return
                if tunnel_proc.stdout:
                    def on_line(line):
                        url = extract_public_url(line)
                        if url:
                            announce(url)

                    threading.Thread(
                        target=_stream_output,
                        args=(tunnel_proc.stdout, tunnel_kind, on_line),
                        kwargs={"quiet": True},
                        daemon=True,
                    ).start()
                if tunnel_kind == "ngrok":
                    url = get_ngrok_url_from_api()
                    if url:
                        announce(url)
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
