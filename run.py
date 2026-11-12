import importlib.util
import os
import signal
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")
FRONTEND = os.path.join(ROOT, "frontend")

procs = []


def cleanup():
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


def ensure_backend_deps():
    required = ("fastapi", "uvicorn")
    missing = [m for m in required if importlib.util.find_spec(m) is None]
    if not missing:
        return
    req_file = os.path.join(BACKEND, "requirements.txt")
    print(f"Installing backend dependencies ({', '.join(missing)} missing)...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])


def ensure_frontend_deps():
    if os.path.isdir(os.path.join(FRONTEND, "node_modules")):
        return
    npm = "npm.cmd" if os.name == "nt" else "npm"
    print("Installing frontend dependencies (first run, this may take a minute)...")
    subprocess.check_call([npm, "install"], cwd=FRONTEND)


def main():
    try:
        ensure_backend_deps()
        ensure_frontend_deps()
    except subprocess.CalledProcessError as e:
        print(f"\nDependency installation failed (exit code {e.returncode}).")
        print("Please install manually:")
        print("  cd backend && pip install -r requirements.txt")
        print("  cd frontend && npm install")
        sys.exit(e.returncode or 1)
    except FileNotFoundError as e:
        print(f"\nRequired tool not found: {e.filename or e}")
        print("Make sure Python/pip and Node.js/npm are installed and on your PATH.")
        sys.exit(1)

    # Backend (FastAPI + WebSockets)
    procs.append(
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
            cwd=BACKEND,
        )
    )

    # Frontend (Vite dev server)
    npm = "npm.cmd" if os.name == "nt" else "npm"
    procs.append(
        subprocess.Popen(
            [npm, "run", "dev"],
            cwd=FRONTEND,
        )
    )

    print()
    print("Backend:  http://localhost:8000  (ws://localhost:8000/ws)")
    print("Frontend: http://localhost:5173")
    print("Press Ctrl+C to stop both.")

    def handle_sigint(sig, frame):
        raise KeyboardInterrupt

    try:
        signal.signal(signal.SIGINT, handle_sigint)
    except Exception:
        pass

    try:
        # wait for either process to exit
        while True:
            for p in procs:
                code = p.poll()
                if code is not None:
                    print(f"\nA process exited (code {code}). Stopping...")
                    return
            try:
                procs[0].wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
