"""The side panels of the right column, in the order of the picker's menu (side_panels.py).

A new panel is a SidePanel subclass in its own module (base.py says how) and one entry here."""
from .used import UsedInDecks
from .versions import SlideVersions
from .visibility import Visibility

PANELS = (UsedInDecks, SlideVersions, Visibility)
