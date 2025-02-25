import logging
from typing import List, Tuple, Dict, Any, Optional
from dockmon.collector import DataCollector

# If not already defined elsewhere, duplicate needed constants:
CPU_THRESHOLD_YELLOW = 50.0
CPU_THRESHOLD_RED = 80.0
MEM_THRESHOLD_YELLOW = 50.0
MEM_THRESHOLD_RED = 80.0

# Also, the HEADERS and STYLE_COLORS are defined globally in your project.
HEADERS = [
    ("NAME", 35),
    ("STATUS", 30),
    ("CREATED_AT", 20),
    ("CPU %", 10),
    ("MEM_USAGE", 25),
    ("NET_IO (RX/TX)", 20),
    ("BLOCK_IO (R/W)", 20)
]

STYLE_COLORS = {
    'red': '#d9534f',
    'yellow': '#f0ad4e',
    'green': '#5cb85c',
    'reverse': 'reverse'
}

class TableRenderer:
    """
    Formats UI fragments based on data provided by DataCollector.
    Handles color selection and text formatting for display.
    """
    def __init__(self, collector: DataCollector, logger: logging.Logger):
        self.collector = collector
        self.logger = logger

    def get_color_for_value(self, value_str: str, yellow_threshold: float, red_threshold: float) -> Optional[str]:
        try:
            value = float(value_str.rstrip('%'))
        except Exception:
            return None
        if value >= red_threshold:
            return STYLE_COLORS['red']
        if value >= yellow_threshold:
            return STYLE_COLORS['yellow']
        return STYLE_COLORS['green']

    def format_with_color(self, text: str, color: Optional[str]) -> Tuple[str, str]:
        return (color, text) if color else ("", text)

    def _build_summary_fragment(self) -> List[Tuple[str, str]]:
        used_mib = self.collector.summary_info.get("mem_used", 0.0)
        limit_mib = self.collector.summary_info.get("mem_limit")
        used_str = self.collector.format_bytes(used_mib)
        limit_str = "unlimited" if limit_mib is None else self.collector.format_bytes(limit_mib)
        if limit_mib and limit_mib > 0:
            total_mem_percent = (used_mib / limit_mib) * 100
            mem_color = self.get_color_for_value(f"{total_mem_percent}", MEM_THRESHOLD_YELLOW, MEM_THRESHOLD_RED)
            return [("", "Total Memory Usage: "), self.format_with_color(f"{used_str} / {limit_str}", mem_color)]
        else:
            return [("", f"Total Memory Usage: {used_str} / {limit_str}")]

    def _build_footer_lines(self, summary_fragments: List[Tuple[str, str]]) -> List[List[Tuple[str, str]]]:
        return [
            summary_fragments,
            [("", "Notes: NET_IO = RX / TX, BLOCK_IO = READ / WRITE")],
            [("", "Press 'p' to pause" if not self.collector.paused_event.is_set() else "PAUSED: press 'p' to resume")],
            [("", "Press 'l' for logs (tmux), 'b' for shell (tmux)")],
            [("", "'q' to quit")]
        ]

    def _build_header_lines(self) -> List[List[Tuple[str, str]]]:
        header_fragments = [("", f"{header:<{width}} ") for header, width in HEADERS]
        sep_fragments = [("", "-" * width + " ") for _, width in HEADERS]
        return [header_fragments, sep_fragments]

    def _build_container_lines(self, sorted_names: List[str],
                               local_ps: Dict[str, Any],
                               local_stats: Dict[str, Any]) -> List[List[Tuple[str, str]]]:
        lines = []
        for idx, name in enumerate(sorted_names):
            prefix = "> " if idx == self.collector.current_selection else "  "
            info = local_ps.get(name, {})
            stat = local_stats.get(name, {})
            status = info.get("status", "N/A")
            created = info.get("created", "N/A")
            cpup = stat.get("cpup", "N/A")
            mem = stat.get("mem", "N/A")
            net = stat.get("net", "N/A")
            block = stat.get("block", "N/A")

            cpu_color = self.get_color_for_value(cpup, CPU_THRESHOLD_YELLOW, CPU_THRESHOLD_RED)
            try:
                mem_parts = mem.split('/')
                if len(mem_parts) != 2:
                    mem_color = None
                else:
                    used_mib_local = self.collector.parse_mem_value(mem_parts[0])
                    total_mib_local = self.collector.parse_mem_value(mem_parts[1])
                    if total_mib_local > 0:
                        mem_percent = (used_mib_local / total_mib_local) * 100
                        mem_color = self.get_color_for_value(str(mem_percent), MEM_THRESHOLD_YELLOW, MEM_THRESHOLD_RED)
                    else:
                        mem_color = None
            except Exception:
                mem_color = None

            line_content = [
                f"{prefix}{name:<{HEADERS[0][1]}} {status:<{HEADERS[1][1]}} {created:<{HEADERS[2][1]}} ",
                f"{cpup:<{HEADERS[3][1]}} ",
                f"{mem:<{HEADERS[4][1]}} ",
                f"{net:<{HEADERS[5][1]}} {block:<{HEADERS[6][1]}}"
            ]

            if idx == self.collector.current_selection:
                line_fragments = [
                    ("reverse", line_content[0]),
                    ("reverse", self.format_with_color(line_content[1], cpu_color)[1]),
                    ("reverse", self.format_with_color(line_content[2], mem_color)[1]),
                    ("reverse", line_content[3])
                ]
            else:
                line_fragments = [
                    ("", line_content[0]),
                    self.format_with_color(line_content[1], cpu_color),
                    self.format_with_color(line_content[2], mem_color),
                    ("", line_content[3])
                ]
            lines.append(line_fragments)
        return lines

    def get_table_fragments(self, height: int) -> List[Tuple[str, str]]:
        try:
            with self.collector.data_lock:
                if self.collector.paused_event.is_set() and self.collector.frozen_data:
                    local_ps, local_stats = self.collector.frozen_data
                else:
                    local_ps = self.collector.ps_info.copy()
                    local_stats = self.collector.stats_info.copy()

            summary_fragments = self._build_summary_fragment()
            footer_lines = self._build_footer_lines(summary_fragments)
            header_lines = self._build_header_lines()
            sorted_names = sorted(local_ps.keys())
            container_rows = self._build_container_lines(sorted_names, local_ps, local_stats)
            container_lines = header_lines + container_rows

            available_lines = height - len(footer_lines)
            if len(container_lines) > available_lines:
                container_lines = container_lines[:available_lines - 1]
                container_lines.append([("", "... more containers ...\n")])

            all_fragments: List[Tuple[str, str]] = []
            for line in container_lines:
                all_fragments.extend(line)
                all_fragments.append(("", "\n"))
            for line in footer_lines:
                all_fragments.extend(line)
                all_fragments.append(("", "\n"))

            remaining_lines = height - (len(container_lines) + len(footer_lines))
            for _ in range(remaining_lines):
                all_fragments.append(("", "\n"))
            return all_fragments
        except Exception as e:
            self.collector.logger.exception(f"Error in get_table_fragments: {e}")
            return [("", "Error generating table fragments.\n")]
