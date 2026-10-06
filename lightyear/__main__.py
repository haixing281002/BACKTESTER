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
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("lightyear.server:app", host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
