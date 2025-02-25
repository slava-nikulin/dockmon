#!/usr/bin/env python3
import os
import threading
import sys
import time
import argparse

from dockmon.utils import setup_logging, kill_tmux_session, launch_tmux_session
from dockmon.collector import DataCollector
from dockmon.tui import TuiApp

def main():
    log_file = "/tmp/docker_monitor.log"
    tmux_session = "docker-monitor"

    parser = argparse.ArgumentParser(
        description="DockMon - Terminal-based Docker container monitor"
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging output")
    args = parser.parse_args()

    logger = setup_logging(args.verbose, log_file)

    # If not running in tmux, launch a new tmux session.
    if os.getenv("TMUX") is None:
        cmd = " ".join(sys.argv)
        launch_tmux_session(tmux_session, log_file, cmd)
        sys.exit(0)

    # Otherwise, run the TUI normally.
    stop_event = threading.Event()
    collector = DataCollector(stop_event=stop_event, logger=logger)
    collector.start_collect()
    tui_app = TuiApp(collector, tmux_session, stop_event, logger=logger)
    tui_app.start_ui_refresh()

    try:
        tui_app.run()
    except KeyboardInterrupt:
        stop_event.set()
        kill_tmux_session(tmux_session)
    except Exception as e:
        collector.logger.exception(f"Unexpected error: {e}")
        stop_event.set()
        kill_tmux_session(tmux_session)

if __name__ == "__main__":
    main()
