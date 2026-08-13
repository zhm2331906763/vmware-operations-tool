import sys
import os
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk
from tkinter import messagebox
from src.app import VCenterManagerApp


def _resource_path(relative_path):
    base_path = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return base_path / relative_path


def main():
    root = tk.Tk()
    icon_path = _resource_path('assets/vm_ops_icon.ico')
    if icon_path.exists():
        try:
            root.iconbitmap(str(icon_path))
        except tk.TclError:
            pass
    app = VCenterManagerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
