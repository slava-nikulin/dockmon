import logging
import threading
import subprocess
import signal
import sys
from prompt_toolkit import Application
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.application import get_app
from prompt_toolkit.styles import Style
from dockmon.collector import DataCollector
from dockmon.renderer import TableRenderer, STYLE_COLORS, HEADERS
from typing import Any

# Unified key mappings as a class attribute.
# Each entry: (tuple of keys, lambda(action))
KEY_MAPPINGS = {
    'quit':    (('q', 'й', 'c-c'), lambda event, app: (kill_tmux_session(app.tmux_session), event.app.exit())),
    'pause':   (('p', 'з'),         lambda event, app: app.collector.toggle_pause()),
    'logs':    (('l', 'д'),         lambda event, app: app.open_logs_tab_tmux(sorted(app.collector.ps_info.keys())[app.collector.current_selection])
                                            if sorted(app.collector.ps_info.keys()) else None),
    'shell':   (('b', 'и'),         lambda event, app: app.open_shell_tab_tmux(sorted(app.collector.ps_info.keys())[app.collector.current_selection])
                                            if sorted(app.collector.ps_info.keys()) else None),
    'up':      (('up',),            lambda event, app: setattr(app.collector, 'current_selection',
                                                                max(0, app.collector.current_selection - 1))),
    'down':    (('down',),          lambda event, app: setattr(app.collector, 'current_selection',
                                                                min(len(sorted(app.collector.ps_info.keys())) - 1,
                                                                    app.collector.current_selection + 1))),
}

UI_INTERVAL = 20

def kill_tmux_session(session_name: str) -> None:
    try:
        subprocess.run(["tmux", "kill-session", "-t", session_name], check=True)
    except Exception as e:
        print(f"Failed to kill tmux session '{session_name}': {e}", file=sys.stderr)

class TuiApp:
    """
    Encapsulates the Prompt Toolkit Application, key bindings, and UI refresh logic.
    """
    def __init__(self, collector: DataCollector, tmux_session: str, stop_event: threading.Event, logger: logging.Logger):
        self.collector = collector
        self.tmux_session = tmux_session
        self.stop_event = stop_event
        self.logger = logger
        self.renderer = TableRenderer(collector, logger)
        self.app = self._build_application()

    def _build_application(self) -> Application:
        self.kb = self._setup_key_bindings()
        style = Style.from_dict({
            'red': STYLE_COLORS['red'],
            'yellow': STYLE_COLORS['yellow'],
            'green': STYLE_COLORS['green'],
            'reverse': STYLE_COLORS['reverse']
        })
        text_control = FormattedTextControl(
            text=lambda: self.renderer.get_table_fragments(get_app().output.get_size().rows),
            focusable=True
        )
        window = Window(content=text_control, always_hide_cursor=True)
        layout = Layout(window)
        layout.focus(window)
        return Application(
            layout=layout,
            key_bindings=self.kb,
            full_screen=True,
            enable_page_navigation_bindings=True,
            style=style
        )

    def _setup_key_bindings(self) -> KeyBindings:
        kb = KeyBindings()
        def sig_handler(sig, frame):
            kill_tmux_session(self.tmux_session)
            sys.exit(0)
        signal.signal(signal.SIGINT, sig_handler)
        signal.signal(signal.SIGTERM, sig_handler)
        for action, (keys, func) in KEY_MAPPINGS.items():
            def handler(event, func=func):
                func(event, self)
            for key in keys:
                kb.add(key)(handler)
        return kb

    def open_logs_tab_tmux(self, container_name: str) -> None:
        try:
            output = subprocess.check_output(["docker", "inspect", "-f", "{{.State.Running}}", container_name],
                                               text=True, timeout=5).strip().lower()
            if output == "true":
                cmd = f"docker logs -f {container_name}"
            else:
                cmd = f"docker logs {container_name}; echo 'Container exited. Press Enter to close.'; read"
            subprocess.Popen(["tmux", "new-window", cmd])
        except Exception as e:
            self.collector.logger.exception(f"Error in open_logs_tab_tmux for {container_name}: {e}")

    def open_shell_tab_tmux(self, container_name: str) -> None:
        try:
            shell = "bash"
            try:
                subprocess.check_output(["docker", "exec", container_name, "bash", "-c", "echo OK"],
                                        text=True, timeout=5)
            except Exception:
                self.collector.logger.info(f"bash not available for {container_name}, using sh")
                shell = "sh"
            command = (f"docker exec -it {container_name} {shell} -c "
                       f"'export PS1=\"[{container_name}] \\u@\\h:\\w\\$ \" && exec {shell}'")
            subprocess.Popen(["tmux", "new-window", command])
        except Exception as e:
            self.collector.logger.exception(f"Error in open_shell_tab_tmux for {container_name}: {e}")

    def start_ui_refresh(self) -> None:
        def refresh_ui():
            while not self.stop_event.is_set():
                try:
                    if self.collector.data_updated.wait(timeout=UI_INTERVAL):
                        self.app.invalidate()
                        self.collector.data_updated.clear()
                except Exception as e:
                    self.collector.logger.exception(f"Error in refresh_ui: {e}")
        threading.Thread(target=refresh_ui, daemon=True).start()

    def run(self) -> None:
        self.app.run()
