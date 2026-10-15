"""Create shortcuts for AIUsageTaskbar on Desktop, Start Menu, and app directory."""
from pathlib import Path
import os
import sys
import winreg
from windows_integration import BASE, create_shortcut

def get_desktop_dir() -> Path:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            val, _ = winreg.QueryValueEx(key, "Desktop")
            expanded = os.path.expandvars(val)
            if os.path.isdir(expanded):
                return Path(expanded)
    except Exception:
        pass
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"

def install():
    targets = [
        BASE / "AI_Usage_Monitor.lnk",
        get_desktop_dir() / "AI_Usage_Monitor.lnk",
        Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/AI_Usage_Monitor.lnk",
    ]
    created = []
    for target in targets:
        try:
            create_shortcut(target)
            created.append(target)
        except Exception as e:
            print(f"Failed to create shortcut at {target}: {e}")
    return created

if __name__ == "__main__":
    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    for target in install():
        print("Created shortcut:", target)
