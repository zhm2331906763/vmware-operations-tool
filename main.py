import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk
from tkinter import messagebox
from src.app import VCenterManagerApp

def main():
    root = tk.Tk()
    app = VCenterManagerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()