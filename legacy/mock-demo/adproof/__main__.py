import argparse
import threading
import webbrowser

from .server import DemoServer
from .workflow import AuditManager


def main():
    parser = argparse.ArgumentParser(description="Run the local AdProof mock orchestration demo.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the local app in your default browser.")
    parser.add_argument("--step-delay", type=float, default=0.55, help="Visual pacing per mock call, in seconds.")
    args = parser.parse_args()
    if not 0 <= args.step_delay <= 5:
        parser.error("--step-delay must be between 0 and 5 seconds")
    manager = AuditManager(step_delay=args.step_delay)
    try:
        server = DemoServer(("127.0.0.1", args.port), manager)
    except OSError as error:
        manager.close()
        parser.exit(1, f"Cannot start local demo: {error}. Try another --port.\n")
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"\nAdProof · local orchestration demo\n{url}\nMode: MOCK · no API keys or external services\nPress Ctrl+C to stop.\n", flush=True)
    if args.open:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping AdProof.", flush=True)
    finally:
        server.server_close()
        manager.close()


if __name__ == "__main__":
    main()
