"""Launch the HR Candidate Screening desktop app (also the PyInstaller entry point)."""

import sys

from hr_screening.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
