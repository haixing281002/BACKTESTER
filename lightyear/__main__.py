"""python -m lightyear [--port 8100] [--no-browser]"""
import argparse
import os
import sys
import threading
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    ap = argparse.ArgumentParser(description="Lightyear: the research pipeline as a local web page")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    import uvicorn
    url = f"http://127.0.0.1:{a.port}"
    print(f"Lightyear on {url}  (local only; Ctrl+C to stop)")
    if not a.no_browser:
        def open_when_ready():
            import socket
            import time
            for _ in range(240):                       # wait up to 60 s for the server to listen
                try:
                    socket.create_connection(("127.0.0.1", a.port), timeout=0.5).close()
                    webbrowser.open(url)
                    return
                except OSError:
                    time.sleep(0.25)
        threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run("lightyear.server:app", host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
