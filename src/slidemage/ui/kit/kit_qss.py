"""QSS for the kit widgets, appended to the application stylesheet by
ThemeManager (theme.py).

The widgets in widgets.py carry only object names and dynamic properties
(`tone`, `kind`, `current`, ...); every color lives here and comes from the
tokens, so a light/dark toggle restyles them with the rest of the app and no
widget needs to know the theme. The object names are constants so the two
files cannot drift apart.

Rules are ID- or property-qualified on purpose: the app-wide rules in
theme.py (`QWidget`, `QPushButton`, `QTabBar::tab`, ...) have lower
specificity and are overridden here without touching the old UI.
"""
from __future__ import annotations

from .tokens import (
    FONT_ICONS,
    FONT_MONO,
    FONT_SANS,
    RADIUS_MD,
    RADIUS_PILL,
    RADIUS_SM,
    Tokens,
    with_alpha,
)

CARD = "kitCard"
SEGMENTED = "kitSegmented"
CHIP = "kitChip"
SPLIT = "kitSplit"
SPLIT_DIVIDER = "kitSplitDivider"
SPLIT_CARET = "kitSplitCaret"
ICON = "kitIcon"
ICON_BUTTON = "kitIconButton"
MENU = "kitMenu"
MENU_ROW = "kitMenuRow"
MENU_TEXT = "kitMenuText"
MENU_META = "kitMenuMeta"
MENU_HEADER = "kitMenuHeader"
MENU_SEPARATOR = "kitMenuSeparator"
MENU_SWATCH = "kitMenuSwatch"
TOAST = "kitToast"
TOAST_ACTION = "kitToastAction"
SHEET = "kitSheet"
SHEET_TITLE = "kitSheetTitle"
SHEET_TABS = "kitSheetTabs"
# Workspace top bar (ui/workspace/topbar.py); its styling lives here so that
# all colors stay in one place.
TOPBAR = "kitTopbar"
TOPBAR_STRIP = "kitTopbarStrip"
TOPBAR_DECK = "kitTopbarDeck"
TOPBAR_LABEL = "kitTopbarLabel"
TOPBAR_SAVE = "kitTopbarSave"
# Slide list (ui/workspace/slide_list.py, slide_tree.py).
SLIDES_FIND = "kitSlidesFind"
SLIDES_TREE = "kitSlidesTree"
SLIDES_RENAME = "kitSlidesRename"
SLIDES_NOTE = "kitSlidesNote"
SLIDES_BULK_LABEL = "kitSlidesBulkLabel"

# Centre column (ui/workspace/centre.py and its views).
SURFACE = "kitSurface"
SOURCE = "kitSource"
SOURCE_NOTE = "kitSourceNote"
SOURCE_FILE_NAME = "kitSourceFileName"
SOURCE_BAR = "kitSourceBar"
PREVIEW_TITLE = "kitPreviewTitle"
PREVIEW_ID = "kitPreviewId"
DETAILS_LABEL = "kitDetailsLabel"
DETAILS_VALUE = "kitDetailsValue"
DETAILS_PANEL = "kitDetailsPanel"
DETAILS_HEAD = "kitDetailsHead"
DETAILS_TITLE = "kitDetailsTitle"

CHIP_TONES = ("neutral", "muted", "info", "warning", "error", "ok")


def _chip_colors(t: Tokens, tone: str) -> tuple[str, str]:
    """(background, text) of a chip tone."""
    return {
        "neutral": (t.bg, t.text),
        "muted": (t.bg, t.text_2),
        "info": (t.info_bg, t.info_fg),
        "warning": (t.warning_bg, t.warning_fg),
        "error": (t.error_bg, t.error_fg),
        "ok": (t.ok_bg, t.ok_fg),
    }[tone]


def build_kit_qss(t: Tokens) -> str:
    font = f'font-family: "{FONT_SANS}";'
    mono = f'font-family: "{FONT_MONO}";'
    chips = "\n".join(
        f"""QFrame#{CHIP}[tone="{tone}"] {{ background-color: {bg}; }}
            QFrame#{CHIP}[tone="{tone}"] QLabel {{ color: {fg}; }}"""
        for tone, (bg, fg) in ((n, _chip_colors(t, n)) for n in CHIP_TONES)
    )
    # Active segment of the "View as" control: solid view color, white text.
    view_segments = "\n".join(
        f"""QPushButton[kitSegment="true"][tone="{view}"]:checked {{
                background-color: {t.view_color(view)}; color: #ffffff; border-bottom-color: transparent; }}"""
        for view in ("instructor", "during", "after")
    )
    strips = "\n".join(
        f"""QFrame#{TOPBAR_STRIP}[tone="{view}"] {{ background-color: {t.view_color(view)}; }}"""
        for view in ("instructor", "during", "after")
    )
    return f"""
        QFrame#{CARD} {{
            background-color: {t.surface};
            border-radius: {RADIUS_MD}px;
        }}

        /* Segmented control: a tinted track with the active segment raised
           as a white pill. The prototype's 0 1px 2px shadow is approximated
           by a 1px bottom border (QSS has no shadows). */
        QFrame#{SEGMENTED} {{
            background-color: {t.hover};
            border-radius: {RADIUS_MD}px;
        }}
        QPushButton[kitSegment="true"] {{
            {font}
            font-size: 12px;
            font-weight: 500;
            background-color: transparent;
            color: {t.text_2};
            border: none;
            border-bottom: 1px solid transparent;
            border-radius: {RADIUS_SM}px;
            padding: 5px 10px;
        }}
        QPushButton[kitSegment="true"][mono="true"] {{
            font-family: "Roboto Mono";
            font-size: 11px;
            font-weight: 600;
            padding: 5px 8px;
        }}
        QPushButton[kitSegment="true"]:hover {{
            color: {t.text};
            background-color: transparent;
        }}
        QPushButton[kitSegment="true"]:checked {{
            background-color: {t.surface};
            color: {t.text};
            border-bottom-color: {with_alpha(t.text, 0.18)};
        }}
        {view_segments}

        /* Fonts are set on the container and reach the labels through Qt's
           font propagation; a QSS font rule on the label itself would also
           override the icon labels' Material Icons font. */
        QFrame#{CHIP} {{
            {font}
            font-size: 12px;
            border-radius: {RADIUS_PILL}px;
        }}
        {chips}

        /* Buttons. "primary" is the dark/inverse fill, "secondary" a bordered
           surface button, "ghost" a flat one. */
        QPushButton[kind] {{
            {font}
            font-size: 13px;
            font-weight: 500;
            border-radius: {RADIUS_SM}px;
            padding: 7px 14px;
        }}
        QPushButton[kind="primary"] {{
            background-color: {t.inverse};
            color: {t.on_inverse};
            border: 1px solid {t.inverse};
        }}
        QPushButton[kind="primary"]:hover {{
            background-color: {t.inverse};
            color: {t.on_inverse};
            border-color: {t.text_2};
        }}
        QPushButton[kind="secondary"] {{
            background-color: {t.surface};
            color: {t.text};
            border: 1px solid {t.line};
        }}
        QPushButton[kind="secondary"]:hover {{
            background-color: {t.hover};
            color: {t.text};
        }}
        QPushButton[kind="ghost"] {{
            background-color: transparent;
            color: {t.text};
            border: 1px solid transparent;
        }}
        QPushButton[kind="ghost"]:hover {{
            background-color: {t.hover};
            color: {t.text};
        }}
        QPushButton[kind][compact="true"] {{
            font-size: 12.5px;
            padding: 4px 9px;
        }}
        QPushButton[kind]:disabled {{
            color: {t.text_4};
            background-color: {t.bg};
            border-color: {t.line};
        }}

        QFrame#{SPLIT} {{
            background-color: {t.inverse};
            border-radius: {RADIUS_SM}px;
        }}
        QFrame#{SPLIT} QPushButton {{
            {font}
            font-size: 13px;
            font-weight: 500;
            background-color: transparent;
            color: {t.on_inverse};
            border: none;
            border-radius: 0;
            padding: 7px 12px;
        }}
        QFrame#{SPLIT} QPushButton:hover {{
            background-color: rgba(0,0,0,0.12);
            color: {t.on_inverse};
        }}
        /* The caret is an icon glyph: it needs the icon font back. */
        QFrame#{SPLIT} QPushButton#{SPLIT_CARET} {{
            font-family: "{FONT_ICONS}";
            font-size: 18px;
            font-weight: 400;
            padding: 5px 7px;
        }}
        QFrame#{SPLIT} QFrame#{SPLIT_DIVIDER} {{
            background-color: {with_alpha(t.on_inverse, 0.25)};
        }}

        QLabel#{ICON} {{
            background-color: transparent;
            color: {t.text_2};
        }}
        QToolButton#{ICON_BUTTON} {{
            background-color: transparent;
            color: {t.text};
            border: none;
            border-radius: {RADIUS_SM}px;
        }}
        QToolButton#{ICON_BUTTON}:hover, QToolButton#{ICON_BUTTON}[active="true"] {{
            background-color: {t.hover};
        }}
        QToolButton#{ICON_BUTTON}:disabled {{
            color: {t.text_4};
        }}

        /* Popover menu. A top-level popup, so it cannot cast a shadow
           without a translucent window (black corners on X11 without a
           compositor); a 1px line border does the job instead. */
        QFrame#{MENU} {{
            background-color: {t.surface};
            border: 1px solid {t.line};
            border-radius: {RADIUS_MD}px;
        }}
        QWidget#{MENU_ROW} {{
            {font}
            font-size: 13px;
            background-color: transparent;
            border-radius: {RADIUS_SM}px;
        }}
        QWidget#{MENU_ROW}:hover, QWidget#{MENU_ROW}[current="true"] {{
            background-color: {t.hover};
        }}
        QWidget#{MENU_ROW} QLabel {{
            color: {t.text};
        }}
        QWidget#{MENU_ROW} QLabel#{MENU_META} {{
            font-size: 11.5px;
            color: {t.text_3};
        }}
        QWidget#{MENU_ROW}[tone="danger"] QLabel#{MENU_TEXT} {{
            color: {t.error};
        }}
        QWidget#{MENU_ROW}[off="true"] QLabel, QWidget#{MENU_ROW}[off="true"] QLabel#{MENU_TEXT} {{
            color: {t.text_4};
        }}
        QLabel#{MENU_HEADER} {{
            {font}
            font-size: 11px;
            font-weight: 500;
            color: {t.text_3};
            padding: 6px 10px 2px 10px;
        }}
        QFrame#{MENU_SEPARATOR} {{
            background-color: {t.line};
            border: none;
        }}

        QFrame#{MENU_SWATCH} {{
            border: 1px solid {t.line};
            border-radius: 3px;
        }}

        QFrame#{TOAST} {{
            {font}
            font-size: 12.5px;
            background-color: {t.inverse};
            border-radius: {RADIUS_MD}px;
        }}
        QFrame#{TOAST}[error="true"] {{
            background-color: {t.error};
        }}
        QFrame#{TOAST} QLabel {{
            color: {t.on_inverse};
        }}
        QFrame#{TOAST}[error="true"] QLabel {{
            color: #ffffff;
        }}
        QPushButton#{TOAST_ACTION} {{
            {font}
            font-size: 12.5px;
            font-weight: 500;
            background-color: {with_alpha(t.on_inverse, 0.14)};
            color: {t.on_inverse};
            border: none;
            border-radius: {RADIUS_SM}px;
            padding: 4px 10px;
        }}
        QPushButton#{TOAST_ACTION}:hover {{
            background-color: {with_alpha(t.on_inverse, 0.28)};
            color: {t.on_inverse};
        }}
        QFrame#{TOAST}[error="true"] QPushButton#{TOAST_ACTION} {{
            background-color: rgba(255,255,255,0.18);
            color: #ffffff;
        }}

        QDialog#{SHEET} {{
            background-color: {t.surface};
        }}
        QDialog#{SHEET} QStackedWidget, QDialog#{SHEET} QTabBar {{
            background-color: transparent;
        }}
        QLabel#{SHEET_TITLE} {{
            {font}
            font-size: 18px;
            font-weight: 500;
            color: {t.text};
        }}
        QTabBar#{SHEET_TABS} {{
            background-color: transparent;
        }}
        QTabBar#{SHEET_TABS}::tab {{
            {font}
            font-size: 13px;
            font-weight: 500;
            background-color: transparent;
            color: {t.text_3};
            border: none;
            border-bottom: 2px solid transparent;
            padding: 8px 14px;
        }}
        QTabBar#{SHEET_TABS}::tab:hover {{
            color: {t.text};
        }}
        QTabBar#{SHEET_TABS}::tab:selected {{
            color: {t.text};
            border-bottom: 2px solid {t.inverse};
            background-color: transparent;
        }}

        /* Top bar: white surface with a hairline, and a 3px strip below it
           in the color of the view being edited. */
        QFrame#{TOPBAR} {{
            background-color: {t.surface};
            border-bottom: 1px solid {t.line};
        }}
        QFrame#{TOPBAR_STRIP} {{
            background-color: {t.line};
        }}
        {strips}
        QFrame#{TOPBAR_DECK} {{
            background-color: transparent;
            {font}
            font-size: 14px;
            font-weight: 600;
            border-radius: {RADIUS_SM}px;
        }}
        QFrame#{TOPBAR_DECK}:hover, QFrame#{TOPBAR_DECK}[active="true"] {{
            background-color: {t.hover};
        }}
        QFrame#{TOPBAR_DECK} QLabel {{
            color: {t.text};
        }}
        QFrame#{TOPBAR_DECK} QLabel#{ICON} {{
            color: {t.text_2};
        }}
        QLabel#{TOPBAR_LABEL} {{
            {font}
            font-size: 12px;
            color: {t.text_3};
        }}
        QLabel#{TOPBAR_SAVE} {{
            {font}
            font-size: 11.5px;
            color: {t.text_3};
        }}

        /* Slide list: the find box is a white field on the grey page, the
           tree draws its own rows (slide_tree.py). */
        QLineEdit#{SLIDES_FIND} {{
            {font}
            font-size: 14px;
            background-color: {t.surface};
            color: {t.text};
            border: none;
            border-radius: {RADIUS_SM}px;
            padding: 0 12px;
            min-height: 40px;
        }}
        QLineEdit#{SLIDES_RENAME} {{
            {font}
            font-size: 12px;
            font-weight: 600;
            background-color: {t.surface};
            color: {t.text};
            border: 1.5px solid {t.info};
            border-radius: {RADIUS_SM}px;
            padding: 0 8px;
        }}
        QTreeWidget#{SLIDES_TREE} {{
            background-color: transparent;
            border: none;
            outline: none;
        }}
        QTreeWidget#{SLIDES_TREE} QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 0;
        }}
        QTreeWidget#{SLIDES_TREE} QScrollBar::handle:vertical {{
            background: {t.text_4};
            border-radius: 4px;
            min-height: 24px;
        }}
        QTreeWidget#{SLIDES_TREE} QScrollBar::add-line:vertical,
        QTreeWidget#{SLIDES_TREE} QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QLabel#{SLIDES_NOTE} {{
            {font}
            font-size: 12.5px;
            color: {t.text_3};
            padding: 16px 8px;
        }}
        QLabel#{SLIDES_BULK_LABEL} {{
            {font}
            font-size: 13px;
            font-weight: 500;
            color: {t.text};
        }}

        /* Centre column: containers are transparent on the white card, so a
           plain QFrame doesn't take the page color of the app-wide rule. */
        #{SURFACE} {{
            background-color: transparent;
        }}
        QFrame#{SOURCE_BAR} {{
            background-color: transparent;
            border-bottom: 1px solid {t.line};
        }}
        QPlainTextEdit#{SOURCE} {{
            {mono}
            font-size: 13px;
            background-color: {t.surface};
            color: {t.text};
            border: none;
        }}
        QPlainTextEdit#{SOURCE} QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 0;
        }}
        QPlainTextEdit#{SOURCE} QScrollBar::handle:vertical {{
            background: {t.text_4};
            border-radius: 4px;
            min-height: 24px;
        }}
        QPlainTextEdit#{SOURCE} QScrollBar::add-line:vertical,
        QPlainTextEdit#{SOURCE} QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QLabel#{SOURCE_NOTE} {{
            {font}
            font-size: 12px;
            color: {t.text_3};
        }}
        QLabel#{SOURCE_FILE_NAME} {{
            {mono}
            font-size: 12px;
            color: {t.text};
        }}

        QLabel#{PREVIEW_TITLE} {{
            {font}
            font-size: 13px;
            font-weight: 600;
            color: {t.text};
        }}
        QLabel#{PREVIEW_ID} {{
            {mono}
            font-size: 12px;
            font-weight: 500;
            color: {t.text_2};
        }}

        QLabel#{DETAILS_LABEL} {{
            {font}
            font-size: 12.5px;
            color: {t.text_3};
        }}
        QLabel#{DETAILS_VALUE} {{
            {font}
            font-size: 12.5px;
            color: {t.text};
        }}
        QLabel#{DETAILS_TITLE} {{
            {font}
            font-size: 18px;
            font-weight: 500;
            color: {t.text};
        }}
        QScrollArea#{SURFACE} QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 0;
        }}
        QScrollArea#{SURFACE} QScrollBar::handle:vertical {{
            background: {t.text_4};
            border-radius: 4px;
            min-height: 24px;
        }}
        QScrollArea#{SURFACE} QScrollBar::add-line:vertical,
        QScrollArea#{SURFACE} QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QFrame#{DETAILS_PANEL} {{
            background-color: {t.bg};
            border-radius: {RADIUS_MD}px;
        }}
        QFrame#{DETAILS_PANEL} QLabel {{
            {font}
            font-size: 12.5px;
            color: {t.text};
        }}
        QLabel#{DETAILS_HEAD} {{
            {font}
            font-size: 13px;
            font-weight: 600;
            color: {t.text};
        }}
    """