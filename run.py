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


def main():
    if not os.path.isdir(os.path.join(FRONTEND, "node_modules")):
        print("Note: frontend dependencies not found. Run once:")
        print("  cd frontend && npm install")
        print()

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
