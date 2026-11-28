# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
# PyInstaller entry script of SlideMage Presenter (packaging/slidemage_presenter.spec).
import time

START = time.perf_counter()      # for SLIDEMAGE_PRESENTER_TIMING (presenter_app.py): time spent before main() runs

import sys

from slidemage import presenter_app

presenter_app.PROCESS_START = START
sys.exit(presenter_app.main())
