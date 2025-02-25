import threading
import subprocess
import time
import datetime
import logging
import re
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Tuple, Any

# Local constants used only in this module.
SUBPROCESS_TIMEOUT = 5
FETCH_INTERVAL=5
DATE_OUTPUT_FORMAT = "%Y-%m-%d %H:%M"

def run_subprocess(cmd: list[str]) -> str:
    """Run a subprocess command with a timeout."""
    return subprocess.check_output(cmd, text=True, timeout=SUBPROCESS_TIMEOUT)

class DataCollector:
    def __init__(self, stop_event: threading.Event, logger: logging.Logger):
        self.ps_info: Dict[str, Dict[str, str]] = {}
        self.stats_info: Dict[str, Dict[str, str]] = {}
        self.summary_info: Dict[str, Any] = {}
        self.frozen_data: Optional[Tuple[Dict, Dict]] = None
        self.data_lock = threading.Lock()
        self.current_selection = 0
        self.paused_event = threading.Event()  # Not set means running; set means paused.
        self.logger = logger
        self.data_updated = threading.Event()
        self.stop_event = stop_event

    def start_collect(self) -> None:
        """Starts background threads for collecting Docker data."""
        def fetch_wrapper(fetch_func):
            while not self.stop_event.is_set():
                self.logger.debug(f"Starting fetch with {fetch_func.__name__}")
                try:
                    fetch_func()
                    self.logger.debug(f"Finished fetch with {fetch_func.__name__}")
                except Exception as e:
                    self.logger.exception(f"Error in {fetch_func.__name__}: {e}")
                time.sleep(FETCH_INTERVAL)
        threading.Thread(target=fetch_wrapper, args=(self.fetch_ps_info,), daemon=True).start()
        threading.Thread(target=fetch_wrapper, args=(self.fetch_stats_info,), daemon=True).start()
        threading.Thread(target=fetch_wrapper, args=(self.fetch_summary_info,), daemon=True).start()

    def notify_data_update(self) -> None:
        self.data_updated.set()

    def fetch_ps_info(self) -> None:
        try:
            output = run_subprocess(["docker", "ps", "-a", "--format", "{{.Names}}||{{.Status}}||{{.CreatedAt}}"])
            new_ps = {}
            for line in output.strip().splitlines():
                parts = line.split("||")
                if len(parts) >= 3:
                    name, status, created = (p.strip() for p in parts)
                    new_ps[name] = {"status": status, "created": self.parse_date(created)}
            with self.data_lock:
                self.ps_info = new_ps
            self.notify_data_update()
        except Exception as e:
            self.logger.exception(f"Error in fetch_ps_info: {e}")

    def fetch_stats_info(self) -> None:
        try:
            output = run_subprocess([
                "docker", "stats", "--no-stream", "--format",
                "{{.Name}}||{{.CPUPerc}}||{{.MemUsage}}||{{.NetIO}}||{{.BlockIO}}"
            ])
            new_stats = {}
            for line in output.strip().splitlines():
                parts = line.split("||")
                if len(parts) >= 5:
                    name, cpup, mem, net, block = (p.strip() for p in parts)
                    new_stats[name] = {
                        "cpup": cpup,
                        "mem": self.reformat_mem_usage(mem),
                        "net": net,
                        "block": block
                    }
            with self.data_lock:
                self.stats_info = new_stats
            self.notify_data_update()
        except Exception as e:
            self.logger.exception(f"Error in fetch_stats_info: {e}")

    def fetch_summary_info(self) -> None:
        try:
            total_used = 0.0
            total_limit = 0.0
            with self.data_lock:
                data = self.stats_info.copy()
            for s in data.values():
                mem_str = s.get("mem", "")
                parts = mem_str.split("/")
                if len(parts) == 2:
                    used_str, limit_str = [p.strip() for p in parts]
                    total_used += self.parse_mem_value(used_str)
                    total_limit += self.parse_mem_value(limit_str)
            with self.data_lock:
                self.summary_info = {
                    "mem_used": total_used,
                    "mem_limit": total_limit if total_limit > 0 else None
                }
            self.notify_data_update()
        except Exception as e:
            self.logger.exception(f"Error in fetch_summary_info: {e}")

    def toggle_pause(self) -> None:
        with self.data_lock:
            if self.paused_event.is_set():
                self.paused_event.clear()
                self.frozen_data = None
            else:
                self.paused_event.set()
                self.frozen_data = (self.ps_info.copy(), self.stats_info.copy())

    def parse_date(self, date_str: str) -> str:
        try:
            trimmed = date_str.strip()[:19]  # "YYYY-MM-DD HH:MM:SS"
            dt = datetime.datetime.strptime(trimmed, "%Y-%m-%d %H:%M:%S")
            return dt.strftime(DATE_OUTPUT_FORMAT)
        except Exception as e:
            self.logger.exception(f"Error parsing date '{date_str}': {e}")
            return date_str

    def parse_mem_value(self, s: str) -> float:
        try:
            s = s.strip()
            s_clean = s.upper().replace(" ", "")
            if s_clean in ("N/A", "NA", "N", "A"):
                return 0.0
            match = re.match(r"([0-9.]+)([A-Z]+)", s_clean)
            if not match:
                raise ValueError(f"Invalid memory string: {s}")
            num_str, unit = match.groups()
            value = float(num_str)
            if unit == "GIB":
                return value * 1024
            elif unit == "MIB":
                return value
            elif unit == "KIB":
                return value / 1024
            else:
                raise ValueError(f"Unknown memory unit: {unit}")
        except Exception as e:
            self.logger.exception(f"Error parsing mem value '{s}': {e}")
            return 0.0

    def format_bytes(self, num: float) -> str:
        try:
            for unit in ['MiB', 'GiB', 'TiB']:
                if num < 1024:
                    return f"{num:.1f}{unit}"
                num /= 1024
            return f"{num:.1f}PiB"
        except Exception as e:
            self.logger.exception(f"Error formatting bytes '{num}': {e}")
            return str(num)

    def reformat_mem_usage(self, mem_usage_str: str) -> str:
        try:
            parts = mem_usage_str.split("/")
            if len(parts) != 2:
                return mem_usage_str
            used_str, limit_str = [p.strip() for p in parts]
            used_mib = self.parse_mem_value(used_str)
            limit_mib = self.parse_mem_value(limit_str)
            return f"{self.format_bytes(used_mib)} / {self.format_bytes(limit_mib)}"
        except Exception as e:
            self.logger.exception(f"Error reformatting mem usage '{mem_usage_str}': {e}")
            return mem_usage_str
