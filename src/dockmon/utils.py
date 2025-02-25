import os
import subprocess
import sys
import logging

def setup_logging(verbose: bool, log_file: str) -> logging.Logger:
    # Always clear the log file at startup.
    with open(log_file, "w") as f:
        pass
    os.chmod(log_file, 0o666)

    log_level = logging.DEBUG if verbose else logging.INFO
    logger = logging.getLogger("dockmon")
    logger.handlers.clear()
    logger.setLevel(log_level)
    file_handler = logging.FileHandler(log_file, mode='a')
    file_handler.setLevel(log_level)
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    # Optionally, suppress overly verbose loggers.
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('docker').setLevel(logging.WARNING)
    return logger


def kill_tmux_session(session_name: str) -> None:
    """
    Kill the tmux session with the given name.
    """
    try:
        subprocess.run(["tmux", "kill-session", "-t", session_name], check=True)
    except Exception as e:
        logging.exception(f"Failed to kill tmux session '{session_name}': {e}")

def launch_tmux_session(tmux_session: str, log_file: str, command: str) -> None:
    """
    Creates a new tmux session with two windows and attaches to it.
    The 'monitor' window will run the provided command.
    """
    import subprocess, sys

    # Kill any existing session with the same name.
    subprocess.run(["tmux", "kill-session", "-t", tmux_session], check=False)
    
    # Create a new detached session with window "monitor".
    subprocess.run(["tmux", "new-session", "-d", "-s", tmux_session, "-n", "monitor"], check=True)
    
    # Create the second window "script-logs" that tails the log file.
    subprocess.run(["tmux", "new-window", "-t", tmux_session, "-n", "script-logs"], check=True)
    subprocess.run(["tmux", "send-keys", "-t", f"{tmux_session}:script-logs",
                    f"clear; tail -f {log_file}", "Enter"], check=True)
    
    # In the "monitor" window, run the original command with all arguments.
    subprocess.run(["tmux", "select-window", "-t", f"{tmux_session}:monitor"], check=True)
    subprocess.run(["tmux", "send-keys", "-t", f"{tmux_session}:monitor", command, "Enter"], check=True)
    
    # Attach to the tmux session.
    subprocess.run(["tmux", "attach-session", "-t", tmux_session], check=True)

