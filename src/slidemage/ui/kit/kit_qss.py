"""The application stylesheet, built from the tokens by ThemeManager (theme.py).

The widgets in widgets.py carry only object names and dynamic properties
(`tone`, `kind`, `current`, ...); every color lives here and comes from the
tokens, so a light/dark toggle restyles them with the rest of the app and no
widget needs to know the theme. The object names are constants so the two
files cannot drift apart.

The first rules are the base: plain widgets and the form controls (line edits,
combos, spin boxes, checkboxes, scroll bars, ...) look the same everywhere
without any per-widget code. The kit's own rules after them are ID- or
property-qualified on purpose: they have the higher specificity and override
the base where a widget needs to differ.
"""
from __future__ import annotations

from collections.abc import Mapping

from .tokens import (
    FONT_ICONS,
    FONT_MONO,
    FONT_SANS,
    RADIUS_MD,
    RADIUS_PILL,
    RADIUS_SM,
    VIEWS,
    Tokens,
    with_alpha,
)

CARD = "kitCard"
SEGMENTED = "kitSegmented"
CHIP = "kitChip"
TOGGLE_CHIP = "kitToggleChip"
SEGMENT_BADGE = "kitSegmentBadge"
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
MENU_COLUMN = "kitMenuColumn"
MENU_FOOTER = "kitMenuFooter"
MENU_NOTE = "kitMenuNote"
MENU_SWATCH = "kitMenuSwatch"
TOAST = "kitToast"
TOAST_ACTION = "kitToastAction"
SHEET = "kitSheet"
SHEET_TITLE = "kitSheetTitle"
MODE_BADGE = "kitModeBadge"
MODE_BADGE_TEXT = "kitModeBadgeText"
SHEET_TABS = "kitSheetTabs"
FIELD_LABEL = "kitFieldLabel"
THUMB = "kitThumb"
THUMB_CAPTION = "kitThumbCaption"
# Command palette (ui/workspace/palette.py).
PALETTE = "kitPalette"
PALETTE_CARD = "kitPaletteCard"
PALETTE_HEAD = "kitPaletteHead"
PALETTE_INPUT = "kitPaletteInput"
PALETTE_KEYS = "kitPaletteKeys"
PALETTE_FOOT = "kitPaletteFoot"
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
AI_PANEL = "kitAiPanel"
AI_ROW = "kitAiRow"
DIFF_OLD = "kitDiffOld"
DIFF_NEW = "kitDiffNew"
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
# Side panels (ui/workspace/side_panels.py, panels/).
PANEL_PICKER = "kitPanelPicker"
PANEL_BOX = "kitPanelBox"
PANEL_ROW = "kitPanelRow"
PANEL_MONO = "kitPanelMono"
PANEL_CAPTION = "kitPanelCaption"
PANEL_MISSING = "kitPanelMissing"
MATRIX_HEAD = "kitMatrixHead"
MATRIX_SLOT = "kitMatrixSlot"
MATRIX_CELL = "kitMatrixCell"
# Compile job panel and Log drawer (ui/workspace/job_panel.py, log_drawer.py).
LIST_BOX = "kitListBox"
# A clickable row with an icon, a name and a second line (project picker, "No decks").
ROW_BUTTON = "kitRowButton"
ROW_NAME = "kitRowName"
JOB_CARD = "kitJobCard"
JOB_TITLE = "kitJobTitle"
JOB_SUB = "kitJobSub"
JOB_PCT = "kitJobPct"
JOB_BAR = "kitJobBar"
IMAGE_LIST = "kitImageList"
# An image on its white background (a slide's), with a thin outline that shows where it ends.
IMAGE_PREVIEW = "kitImagePreview"
LOG_DRAWER = "kitLogDrawer"
LOG_HEAD = "kitLogHead"
LOG_TITLE = "kitLogTitle"
LOG_TEXT = "kitLogText"
LOG_ACTION = "kitLogAction"
LOG_ERROR = "kitLogError"
# Chat (ui/workspace/chat/).
CHAT_USER = "kitChatUser"
CHAT_TEXT = "kitChatText"
CHAT_MODEL = "kitChatModel"
CHAT_TOOL = "kitChatTool"
CHAT_TOOL_NAME = "kitChatToolName"
CHAT_TOOL_SUMMARY = "kitChatToolSummary"
CHAT_TOOL_BODY = "kitChatToolBody"
CHAT_DIFF = "kitChatDiff"
CHAT_DIFF_LINE = "kitChatDiffLine"
CHAT_NOTICE = "kitChatNotice"
CHAT_SUGGESTION = "kitChatSuggestion"

# The AI switch of the top bar and its popovers (ui/workspace/ai_switch.py, ai_popups.py, ai_setup.py).
AI_SWITCH = "kitAiSwitch"
AI_SWITCH_STATE = "kitAiSwitchState"
AI_POPUP_TITLE = "kitAiPopupTitle"
AI_POPUP_TEXT = "kitAiPopupText"
AI_POPUP_LINK = "kitAiPopupLink"
AI_SETUP_HEAD = "kitAiSetupHead"
AI_SETUP_CELL = "kitAiSetupCell"
# The assistant card's header, the running-task pill and the Claude Code setup card (ui/workspace/assistant*.py).
ASSISTANT_TITLE = "kitAssistantTitle"
ASSISTANT_SUB = "kitAssistantSub"
ASSISTANT_TARGET = "kitAssistantTarget"
TASK_PILL = "kitTaskPill"
# The task card (ui/workspace/task_card.py).
TASK_CARD = "kitTaskCard"
TASK_TITLE = "kitTaskTitle"
TASK_ROUTE = "kitTaskRoute"
TASK_STATE = "kitTaskState"
TASK_ELAPSED = "kitTaskElapsed"
TASK_STEP = "kitTaskStep"
CLOUD_CARD = "kitCloudCard"

WARNING_LABEL = "warningLabel"

# Images the form controls draw (QSS has no glyphs): name -> (Material Icons name, token that colors it,
# glyph size in px, image size in px).
KIT_ICONS = {
    "check": ("check", "on_inverse", 15, 13),
    "radio": ("fiber_manual_record", "inverse", 11, 13),
    "chevron_down": ("expand_more", "text_3", 18, 18),
    "chevron_up": ("expand_less", "text_3", 18, 18),
}

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


def build_kit_qss(t: Tokens, icons: Mapping[str, str]) -> str:
    """`icons` maps the names in KIT_ICONS to image files, for the arrows and ticks of the controls."""
    font = f'font-family: "{FONT_SANS}";'
    mono = f'font-family: "{FONT_MONO}";'

    def text(selector: str, size: float, color: str, weight: int | None = None, family: str = font) -> str:
        """A text style: the family, size, optional weight and color of `selector`."""
        bold = f" font-weight: {weight};" if weight else ""
        return f"{selector} {{ {family} font-size: {size}px;{bold} color: {color}; }}"

    chips = "\n".join(
        f"""QFrame#{CHIP}[tone="{tone}"] {{ background-color: {bg}; }}
            QFrame#{CHIP}[tone="{tone}"] QLabel {{ color: {fg}; }}"""
        for tone, (bg, fg) in ((n, _chip_colors(t, n)) for n in CHIP_TONES)
    )
    toggle_chips = "\n".join(
        f"""QPushButton#{TOGGLE_CHIP}[tone="{view}"]:checked:enabled {{
                background-color: {t.view_tint(view)}; color: {t.view_color(view)};
                border-color: {t.view_color(view)}; }}"""
        for view in VIEWS
    )
    # Active segment of the "View as" control: solid view color, white text.
    view_segments = "\n".join(
        f"""QPushButton[kitSegment="true"][tone="{view}"]:checked {{
                background-color: {t.view_color(view)}; color: {t.on_solid}; border-bottom-color: transparent; }}"""
        for view in VIEWS
    )
    strips = "\n".join(
        f"""QFrame#{TOPBAR_STRIP}[tone="{view}"] {{ background-color: {t.view_color(view)}; }}"""
        for view in VIEWS
    )
    # The matrix cells and their headings take the color of their view.
    matrix_cells = "\n".join(
        f"""QPushButton#{MATRIX_CELL}[view="{view}"]:checked {{
                background-color: {t.view_color(view)}; border-color: {t.view_color(view)}; }}
            QLabel#{MATRIX_HEAD}[view="{view}"] {{ color: {t.view_color(view)}; }}"""
        for view in VIEWS
    )
    return f"""
        /* The base: widgets the kit has no rule for (message boxes, file
           dialogs, plain labels and buttons). The kit's own rules below are
           ID- or property-qualified and win over these. */
        QMainWindow, QWidget {{
            background-color: {t.bg};
            color: {t.text};
        }}
        QDialog {{
            background-color: {t.bg};
        }}
        QLabel {{
            background-color: transparent;
        }}
        QLabel#{WARNING_LABEL} {{
            color: {t.error};
        }}
        QPushButton {{
            {font}
            font-size: 13px;
            background-color: {t.surface};
            color: {t.text};
            border: 1px solid {t.line};
            border-radius: {RADIUS_SM}px;
            padding: 4px 10px;
        }}
        QPushButton:hover {{
            background-color: {t.hover};
        }}
        QPushButton:disabled {{
            color: {t.text_4};
        }}
        QToolTip {{
            {font}
            font-size: 12px;
            background-color: {t.inverse};
            color: {t.on_inverse};
            border: none;
            padding: 4px 8px;
        }}
        QMenu {{
            {font}
            font-size: 13px;
            background-color: {t.surface};
            color: {t.text};
            border: 1px solid {t.line};
            border-radius: {RADIUS_SM}px;
            padding: 4px;
        }}
        QMenu::item {{
            padding: 5px 24px 5px 12px;
            border-radius: {RADIUS_SM}px;
        }}
        QMenu::item:selected {{
            background-color: {t.hover};
        }}
        QMenu::item:disabled {{
            color: {t.text_4};
        }}
        QMenu::separator {{
            height: 1px;
            background-color: {t.line};
            margin: 4px 6px;
        }}

        /* Form controls, everywhere: a field on the page color with a line
           under it (prototype v3), a ring when it has the focus. */
        QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
            {font}
            font-size: 13.5px;
            background-color: {t.bg};
            color: {t.text};
            border: 1px solid transparent;
            border-bottom-color: {t.text_4};
            border-radius: {RADIUS_SM}px;
            padding: 5px 9px;
            selection-background-color: {t.info};
            selection-color: {t.on_solid};
            placeholder-text-color: {t.text_3};
        }}
        QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
        QComboBox:focus, QComboBox:on {{
            border-color: {t.info};
        }}
        QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled, QSpinBox:disabled,
        QDoubleSpinBox:disabled, QComboBox:disabled {{
            color: {t.text_4};
            border-bottom-color: {t.line};
        }}
        QComboBox {{
            padding-right: 28px;
        }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: center right;
            width: 26px;
            border: none;
        }}
        QComboBox::down-arrow {{
            image: url({icons["chevron_down"]});
            width: 18px;
            height: 18px;
        }}
        QComboBox QAbstractItemView {{
            {font}
            font-size: 13px;
            background-color: {t.surface};
            color: {t.text};
            border: 1px solid {t.line};
            border-radius: {RADIUS_SM}px;
            padding: 4px;
            outline: none;
            selection-background-color: {t.hover};
            selection-color: {t.text};
        }}
        QComboBox QAbstractItemView::item {{
            min-height: 22px;
            padding: 2px 8px;
        }}
        QSpinBox, QDoubleSpinBox {{
            padding-right: 24px;
        }}
        QSpinBox::up-button, QDoubleSpinBox::up-button {{
            subcontrol-origin: border;
            subcontrol-position: top right;
            width: 20px;
            border: none;
        }}
        QSpinBox::down-button, QDoubleSpinBox::down-button {{
            subcontrol-origin: border;
            subcontrol-position: bottom right;
            width: 20px;
            border: none;
        }}
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
            image: url({icons["chevron_up"]});
            width: 14px;
            height: 14px;
        }}
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
            image: url({icons["chevron_down"]});
            width: 14px;
            height: 14px;
        }}
        QCheckBox, QRadioButton {{
            {font}
            font-size: 13px;
            background-color: transparent;
            color: {t.text};
            spacing: 8px;
        }}
        QCheckBox:disabled, QRadioButton:disabled {{
            color: {t.text_4};
        }}
        QCheckBox::indicator, QRadioButton::indicator {{
            width: 16px;
            height: 16px;
            border: 1.5px solid {t.text_3};
            background-color: transparent;
        }}
        QCheckBox::indicator {{
            border-radius: {RADIUS_SM - 1}px;
        }}
        QRadioButton::indicator {{
            border-radius: 9px;
        }}
        QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
            border-color: {t.text};
        }}
        QCheckBox::indicator:checked {{
            background-color: {t.inverse};
            border-color: {t.inverse};
            image: url({icons["check"]});
        }}
        QRadioButton::indicator:checked {{
            border-color: {t.inverse};
            image: url({icons["radio"]});
        }}
        QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
            border-color: {t.line};
        }}
        QCheckBox::indicator:checked:disabled {{
            background-color: {t.text_4};
            border-color: {t.text_4};
        }}
        QListWidget {{
            {font}
            font-size: 13px;
            background-color: {t.bg};
            color: {t.text};
            border: none;
            border-radius: {RADIUS_MD}px;
            padding: 4px;
            outline: none;
        }}
        QListWidget::item {{
            padding: 5px 8px;
            border-radius: {RADIUS_SM}px;
        }}
        QListWidget::item:hover {{
            background-color: {t.hover};
        }}
        QListWidget::item:selected {{
            background-color: {t.surface};
            color: {t.text};
        }}
        QProgressBar {{
            background-color: {with_alpha(t.text, 0.15)};
            border: none;
            border-radius: 3px;
            text-align: center;
        }}
        QProgressBar::chunk {{
            background-color: {t.inverse};
            border-radius: 3px;
        }}
        QSplitter#{SURFACE}::handle:horizontal {{
            background: {t.line};
            margin: 0 4px;
        }}
        QSplitter#{SURFACE}::handle:horizontal:hover, QSplitter#{SURFACE}::handle:horizontal:pressed {{
            background: {t.text_4};
        }}
        QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 0;
        }}
        QScrollBar:horizontal {{
            background: transparent;
            height: 8px;
            margin: 0;
        }}
        QScrollBar::handle {{
            background: {t.text_4};
            border-radius: 4px;
            min-height: 24px;
            min-width: 24px;
        }}
        QScrollBar::handle:hover {{
            background: {t.text_3};
        }}
        QScrollBar::add-line, QScrollBar::sub-line {{
            width: 0;
            height: 0;
        }}
        QScrollBar::add-page, QScrollBar::sub-page {{
            background: transparent;
        }}

        QFrame#{CARD}, QFrame#{PALETTE_CARD} {{
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
        QPushButton[kitSegment="true"][badge="true"] {{
            padding-right: 22px;
        }}
        QLabel#{SEGMENT_BADGE} {{
            {font}
            font-size: 10px;
            font-weight: 700;
            color: {t.on_solid};
            background-color: {t.error_solid};
            border-radius: 7px;
            padding: 0 4px;
            min-width: 8px;
            min-height: 14px;
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
        /* The Cloud segment of the AI switch, the keyboard ring of a roving control, and the room for an icon. */
        QPushButton[kitSegment="true"][tone="cloud"]:checked {{
            background-color: {t.cloud_solid}; color: {t.on_solid}; border-bottom-color: transparent;
        }}
        QPushButton[kitSegment="true"][withIcon="true"] {{
            padding-left: 30px;
        }}
        /* The keyboard ring (2px, the border grows in the padding so the segment keeps its size). */
        QPushButton[kitSegment="true"]:focus {{
            border: 2px solid {t.focus}; padding: 3px 9px;
        }}
        QPushButton[kitSegment="true"][mono="true"]:focus {{ padding: 3px 6px; }}
        QPushButton[kitSegment="true"][badge="true"]:focus {{ padding-right: 20px; }}
        QPushButton[kitSegment="true"][withIcon="true"]:focus {{ padding-left: 28px; }}
        QLabel#{ICON}[segment="off"] {{ color: {t.text_2}; }}
        QLabel#{ICON}[segment="on"] {{ color: {t.text}; }}
        QLabel#{ICON}[segment="cloud"] {{ color: {t.on_solid}; }}

        /* Fonts are set on the container and reach the labels through Qt's
           font propagation; a QSS font rule on the label itself would also
           override the icon labels' Material Icons font. */
        QFrame#{CHIP} {{
            {font}
            font-size: 12px;
            border-radius: {RADIUS_PILL}px;
        }}
        {chips}

        /* A chip that switches on and off; on, it takes the colors of its view. */
        QPushButton#{TOGGLE_CHIP} {{
            {font}
            font-size: 12px;
            font-weight: 500;
            background-color: transparent;
            color: {t.text_3};
            border: 1px solid {t.line};
            border-radius: {RADIUS_PILL}px;
            padding: 4px 12px;
        }}
        QPushButton#{TOGGLE_CHIP}:hover {{
            background-color: {t.hover};
        }}
        QPushButton#{TOGGLE_CHIP}:checked {{
            background-color: {t.bg};
            color: {t.text};
            border-color: {t.text_3};
        }}
        {toggle_chips}
        QPushButton#{TOGGLE_CHIP}:disabled {{
            color: {t.text_4};
            border-color: {t.line};
        }}

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
        QPushButton[kind="cloud"] {{
            background-color: {t.cloud_solid};
            color: {t.on_solid};
            border: 1px solid {t.cloud_solid};
        }}
        QPushButton[kind="cloud"]:hover {{
            background-color: {t.cloud_solid};
            color: {t.on_solid};
            border-color: {t.cloud_text};
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
        QPushButton[kind]:focus {{ border: 2px solid {t.focus}; padding: 6px 13px; }}
        QPushButton[kind][compact="true"]:focus {{ padding: 3px 8px; }}

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
        QFrame#{SPLIT} QPushButton:focus {{ border: 2px solid {t.focus}; padding: 5px 10px; }}
        QFrame#{SPLIT} QPushButton#{SPLIT_CARET}:focus {{ padding: 3px 5px; }}
        QFrame#{SPLIT} QFrame#{SPLIT_DIVIDER} {{
            background-color: {with_alpha(t.on_inverse, 0.25)};
        }}

        QLabel#{ICON} {{
            background-color: transparent;
            color: {t.text_2};
        }}
        QLabel#{ICON}[tone="error"] {{ color: {t.error}; }}
        QLabel#{ICON}[tone="ok"] {{ color: {t.ok}; }}
        QLabel#{ICON}[tone="muted"] {{ color: {t.text_4}; }}
        QLabel#{ICON}[tone="strong"] {{ color: {t.text}; }}
        QLabel#{ICON}[tone="warning"] {{ color: {t.warning}; }}
        QLabel#{ICON}[tone="local"] {{ color: {t.local_icon}; }}
        QLabel#{ICON}[tone="cloud"] {{ color: {t.cloud_solid}; }}
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
        QToolButton#{ICON_BUTTON}:focus {{ border: 2px solid {t.focus}; }}

        /* Popover menu. A top-level popup, so it cannot cast a shadow
           without a translucent window (black corners on X11 without a
           compositor); a 1px line border does the job instead. */
        QFrame#{MENU} {{
            background-color: {t.surface};
            border: 1px solid {t.line};
            border-radius: {RADIUS_MD}px;
        }}
        QFrame#{MENU} QListWidget {{
            {font}
            font-size: 12.5px;
            background-color: transparent;
            border: none;
            outline: none;
        }}
        QFrame#{MENU} QListWidget::item {{
            padding: 6px 8px;
            border-radius: {RADIUS_SM}px;
            color: {t.text};
        }}
        QFrame#{MENU} QListWidget::item:selected {{
            background-color: {t.hover};
            color: {t.text};
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
            margin: 0 6px;
        }}

        /* The columns layout (PopoverMenu.add_column): denser rows and bigger headers, a hairline
           between the columns and above the footer. */
        QFrame#{MENU_COLUMN}, QFrame#{MENU_FOOTER} {{ border: none; background-color: transparent; }}
        QFrame#{MENU_COLUMN}[divided="true"] {{
            border-left: 1px solid {t.line};
            margin-left: 2px;
            padding-left: 4px;
        }}
        QFrame#{MENU_FOOTER} {{
            border-top: 1px solid {t.line};
            margin-top: 4px;
            padding: 6px 4px 2px 4px;
        }}
        QFrame#{MENU}[columns="true"] QWidget#{MENU_ROW} {{ font-size: 12.5px; }}
        QFrame#{MENU}[columns="true"] QWidget#{MENU_ROW} QLabel#{MENU_META} {{
            {mono}
            font-size: 10.5px;
        }}
        {text(f'QFrame#{MENU}[columns="true"] QLabel#{MENU_HEADER}', 13, t.text_2, 500)}
        QFrame#{MENU}[columns="true"] QLabel#{MENU_HEADER} {{ padding: 8px 10px 3px 10px; }}
        QFrame#{MENU_FOOTER} QWidget#{MENU_ROW} QLabel#{MENU_TEXT} {{ font-weight: 500; }}
        {text(f"QLabel#{MENU_NOTE}", 11.5, t.text_3)}
        QLabel#{MENU_NOTE} {{ padding: 0 8px; }}

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
            background-color: {t.error_solid};
        }}
        QFrame#{TOAST} QLabel {{
            color: {t.on_inverse};
        }}
        QFrame#{TOAST}[error="true"] QLabel {{
            color: {t.on_solid};
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
            background-color: {with_alpha(t.on_solid, 0.18)};
            color: {t.on_solid};
        }}

        QWidget#{PALETTE} {{
            background-color: {with_alpha("#000000", 0.4)};
        }}
        QFrame#{PALETTE_CARD} QScrollArea, QFrame#{PALETTE_CARD} QScrollArea > QWidget > QWidget {{
            background-color: transparent;
            border: none;
        }}
        QFrame#{PALETTE_HEAD} {{
            border-bottom: 1px solid {t.line};
        }}
        QLineEdit#{PALETTE_INPUT} {{
            {font}
            font-size: 16px;
            color: {t.text};
            background-color: transparent;
            border: none;
            padding: 0;
        }}
        QFrame#{PALETTE_FOOT} {{
            border-top: 1px solid {t.line};
        }}
        {text(f"QFrame#{PALETTE_FOOT} QLabel", 11.5, t.text_3)}
        {text(f"QLabel#{PALETTE_KEYS}", 10.5, t.text_3, None, mono)}

        QDialog#{SHEET} {{
            background-color: {t.surface};
        }}
        QDialog#{SHEET} QStackedWidget, QDialog#{SHEET} QTabBar {{
            background-color: transparent;
        }}
        {text(f"QLabel#{SHEET_TITLE}", 18, t.text, 500)}
        /* The read-only route badge under a dialog's title: a grey pill, amber on Cloud. */
        QFrame#{MODE_BADGE} {{ background-color: {t.bg}; border-radius: {RADIUS_PILL}px; }}
        QFrame#{MODE_BADGE}[cloud="true"] {{ background-color: {t.cloud_bg}; }}
        {text(f"QLabel#{MODE_BADGE_TEXT}", 11.5, t.text_2, 500)}
        QFrame#{MODE_BADGE}[cloud="true"] QLabel {{ color: {t.cloud_fg}; }}
        {text(f"QLabel#{FIELD_LABEL}", 13, t.text_2, 500)}
        QFrame#{THUMB} {{
            border: 2px solid {t.line};
            border-radius: {RADIUS_SM + 1}px;
            background-color: transparent;
        }}
        QFrame#{THUMB}[current="true"] {{
            border-color: {t.inverse};
        }}
        QLabel#{THUMB_CAPTION} {{
            {mono}
            font-size: 10.5px;
            color: {t.text_3};
            border: none;
        }}
        QFrame#{THUMB}[current="true"] QLabel#{THUMB_CAPTION} {{
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
            border: 2px solid transparent;
            border-radius: {RADIUS_SM}px;
        }}
        QFrame#{TOPBAR_DECK}:focus {{ border-color: {t.focus}; }}
        QFrame#{TOPBAR_DECK}:hover, QFrame#{TOPBAR_DECK}[active="true"] {{
            background-color: {t.hover};
        }}
        QFrame#{TOPBAR_DECK} QLabel {{
            color: {t.text};
        }}
        QFrame#{TOPBAR_DECK} QLabel#{ICON} {{
            color: {t.text_2};
        }}
        {text(f"QLabel#{TOPBAR_LABEL}", 12, t.text_3)}

        /* The AI switch: its wrapper is outlined while Local and amber while Cloud (the 1.5px outline of the
           prototype is a 2px border here; the padding keeps both the same size). */
        QFrame#{AI_SWITCH} {{
            background-color: transparent;
            border: 1px solid {t.line};
            border-radius: {RADIUS_MD}px;
            padding: 1px;
        }}
        QFrame#{AI_SWITCH}[cloud="true"] {{
            background-color: {t.cloud_bg};
            border: 2px solid {t.cloud_border};
            padding: 0;
        }}
        {text(f"QLabel#{AI_SWITCH_STATE}", 12, t.text_2, 600)}
        QLabel#{AI_SWITCH_STATE}[cloud="true"] {{ color: {t.cloud_fg}; }}
        QFrame#{AI_SWITCH} QToolButton#{ICON_BUTTON}[cloud="true"] {{ color: {t.cloud_fg}; }}
        QFrame#{AI_SWITCH}[cloud="true"] QFrame#{SEGMENTED} {{ background-color: {with_alpha(t.text, 0.06)}; }}

        /* The popovers of the switch (they are kitMenu frames with 16px padding). */
        {text(f"QLabel#{AI_POPUP_TITLE}", 14, t.text, 600)}
        {text(f"QLabel#{AI_POPUP_TEXT}", 13, t.text_2)}
        QPushButton#{AI_POPUP_LINK} {{
            {font} font-size: 12.5px; color: {t.text_2}; text-decoration: underline;
            background-color: transparent; border: 2px solid transparent; border-radius: {RADIUS_SM}px; padding: 0 2px;
        }}
        QPushButton#{AI_POPUP_LINK}:hover {{ color: {t.text}; }}
        QPushButton#{AI_POPUP_LINK}:focus {{ border-color: {t.focus}; }}
        {text(f"QLabel#{AI_SETUP_HEAD}", 12.5, t.text_3, 600)}
        QLabel#{AI_SETUP_HEAD}[active="true"] {{ color: {t.text}; }}
        QFrame#{MENU} QFrame#{LIST_BOX} {{ border-radius: {RADIUS_SM}px; }}
        QComboBox#{AI_SETUP_CELL} {{
            {mono}
            font-size: 12px;
            min-height: 20px;
            padding: 3px 6px;
            padding-right: 22px;
        }}
        QComboBox#{AI_SETUP_CELL}[active="false"] {{ color: {t.text_4}; }}
        QComboBox#{AI_SETUP_CELL}::drop-down {{ width: 20px; }}
        QLabel#{AI_SETUP_CELL} {{
            {mono}
            font-size: 12px;
            color: {t.text_3};
        }}
        {text(f"QLabel#{TOPBAR_SAVE}", 11.5, t.text_3)}

        /* The assistant header: the route's title (amber in Cloud), its model, and the target of the scope. */
        {text(f"QLabel#{ASSISTANT_TITLE}", 14, t.text, 600)}
        QLabel#{ASSISTANT_TITLE}[cloud="true"] {{ color: {t.cloud_fg}; }}
        {text(f"QLabel#{ASSISTANT_SUB}", 12, t.text_2)}
        {text(f"QLabel#{ASSISTANT_TARGET}", 12.5, t.text_2)}
        QFrame#{TASK_PILL} {{ background-color: {t.bg}; border-radius: {RADIUS_SM}px; }}
        {text(f"QFrame#{TASK_PILL} QLabel", 12.5, t.text)}
        QFrame#{TASK_CARD} {{ border: 1px solid {t.line}; border-radius: {RADIUS_MD}px; }}
        {text(f"QLabel#{TASK_TITLE}", 15, t.text, 600)}
        {text(f"QLabel#{TASK_ROUTE}", 12, t.local_fg, None, mono)}
        QLabel#{TASK_ROUTE}[cloud="true"] {{ color: {t.cloud_text}; }}
        {text(f"QLabel#{TASK_STATE}", 13.5, t.text)}
        QLabel#{TASK_STATE}[tone="ok"] {{ color: {t.ok_fg}; }}
        QLabel#{TASK_STATE}[tone="warning"] {{ color: {t.cloud_text}; }}
        QLabel#{TASK_STATE}[tone="error"] {{ color: {t.error}; }}
        QLabel#{TASK_STATE}[tone="muted"] {{ color: {t.text_2}; }}
        {text(f"QLabel#{TASK_ELAPSED}", 12, t.text_3, None, mono)}
        {text(f"QLabel#{TASK_STEP}", 12, t.text_3)}
        QFrame#{CLOUD_CARD} {{
            background-color: {t.cloud_bg};
            border: 1px solid {t.cloud_border};
            border-radius: {RADIUS_MD}px;
        }}
        QFrame#{CLOUD_CARD} QLabel {{ background-color: transparent; color: {t.cloud_fg}; }}
        QFrame#{CLOUD_CARD} QLabel#{ICON} {{ color: {t.cloud_solid}; }}
        {text(f"QFrame#{CLOUD_CARD} QLabel#{ASSISTANT_TITLE}", 14, t.cloud_fg, 600)}

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
        QLabel#{SLIDES_NOTE} {{
            {font}
            font-size: 12.5px;
            color: {t.text_3};
            padding: 16px 8px;
        }}
        {text(f"QLabel#{SLIDES_BULK_LABEL}", 13, t.text, 500)}

        /* Centre column: containers are transparent on the white card, so a
           plain QFrame doesn't take the page color of the app-wide rule. */
        #{SURFACE} {{
            background-color: transparent;
        }}
        QFrame#{SOURCE_BAR}, QFrame#{AI_PANEL} {{
            background-color: transparent;
            border-bottom: 1px solid {t.line};
        }}
        QPlainTextEdit#{SOURCE} {{
            {mono}
            font-size: 13px;
            background-color: {t.surface};
            color: {t.text};
            border: none;
            padding: 0;
        }}
        QFrame#{AI_ROW}, QFrame#{DETAILS_PANEL}, QFrame#{PANEL_BOX}, QFrame#{LIST_BOX}, QFrame#{CHAT_TOOL} {{
            background-color: {t.bg};
            border-radius: {RADIUS_MD}px;
        }}
        {text(f"QFrame#{AI_ROW} QLabel", 12.5, t.text)}
        QFrame#{AI_ROW} QLabel#{DIFF_OLD}, QFrame#{AI_ROW} QLabel#{DIFF_NEW} {{
            {mono}
            font-size: 12px;
            padding: 2px 6px;
            border-radius: 3px;
        }}
        QFrame#{AI_ROW} QLabel#{DIFF_OLD} {{
            background-color: {t.error_bg};
            color: {t.error_fg};
        }}
        QFrame#{AI_ROW} QLabel#{DIFF_NEW} {{
            background-color: {t.ok_bg};
            color: {t.ok_fg};
        }}
        {text(f"QLabel#{SOURCE_NOTE}", 12, t.text_3)}
        {text(f"QLabel#{SOURCE_FILE_NAME}", 12, t.text, None, mono)}

        {text(f"QLabel#{PREVIEW_TITLE}", 13, t.text, 600)}
        {text(f"QLabel#{PREVIEW_ID}", 12, t.text_2, 500, mono)}

        {text(f"QLabel#{DETAILS_LABEL}", 12.5, t.text_3)}
        {text(f"QLabel#{DETAILS_VALUE}", 12.5, t.text)}
        {text(f"QLabel#{DETAILS_TITLE}", 18, t.text, 500)}
        {text(f"QFrame#{DETAILS_PANEL} QLabel", 12.5, t.text)}
        {text(f"QLabel#{DETAILS_HEAD}", 13, t.text, 600)}
    
        /* Side panels: the picker is a grey pill; a panel's content sits in grey boxes
           whose rows are separated by hairlines. */
        QFrame#{PANEL_PICKER} {{
            background-color: {t.bg};
            {font}
            font-size: 12.5px;
            font-weight: 500;
            border: 2px solid transparent;
            border-radius: {RADIUS_SM}px;
        }}
        QFrame#{PANEL_PICKER}:focus {{ border-color: {t.focus}; }}
        QFrame#{PANEL_PICKER}:hover, QFrame#{PANEL_PICKER}[active="true"] {{
            background-color: {t.line};
        }}
        QFrame#{PANEL_PICKER} QLabel {{
            color: {t.text};
        }}
        QFrame#{PANEL_PICKER} QLabel#{ICON} {{
            color: {t.text_3};
        }}
        QFrame#{PANEL_ROW} {{
            background-color: transparent;
            border: none;
            border-bottom: 1px solid {t.line};
        }}
        {text(f"QFrame#{PANEL_BOX} QLabel", 12.5, t.text)}
        QFrame#{PANEL_BOX} QLabel#{DETAILS_LABEL} {{
            color: {t.text_3};
        }}
        QFrame#{PANEL_BOX} QLabel#{PANEL_MONO}, QFrame#{LIST_BOX} QLabel#{PANEL_MONO},
        QDialog#{SHEET} QLabel#{PANEL_MONO} {{
            {mono}
            font-size: 12px;
        }}
        {text(f"QFrame#{PANEL_BOX} QLabel#{PANEL_CAPTION}, QLabel#{PANEL_CAPTION}", 11.5, t.text_3)}
        QLabel#{PANEL_CAPTION}[tone="error"] {{
            color: {t.error};
        }}
        QLabel#{PANEL_CAPTION}[tone="warning"] {{
            color: {t.warning};
        }}
        QFrame#{PANEL_BOX} QLabel#{PANEL_MISSING} {{
            color: {t.error};
        }}
        QLabel#{MATRIX_HEAD} {{
            {font}
            font-size: 11.5px;
            font-weight: 600;
        }}
        QLabel#{MATRIX_HEAD}[current="true"] {{
            background-color: {t.surface};
        }}
        QFrame#{MATRIX_SLOT}[current="true"] {{
            background-color: {t.surface};
        }}
        QPushButton#{MATRIX_CELL} {{
            {font}
            font-size: 11px;
            font-weight: 700;
            color: {t.on_solid};
            background-color: {t.surface};
            border: 1px solid {t.text_4};
            border-radius: {RADIUS_SM}px;
            padding: 0;
        }}
        QPushButton#{MATRIX_CELL}:disabled {{
            background-color: transparent;
            border-color: {t.line};
        }}
        {matrix_cells}

        QFrame#{ROW_BUTTON} {{
            background-color: transparent;
            border-radius: {RADIUS_SM}px;
        }}
        QFrame#{ROW_BUTTON}:hover {{
            background-color: {t.hover};
        }}
        QLabel#{ROW_NAME} {{
            {font}
            font-size: 14px;
            font-weight: 500;
        }}

        /* A grey box of rows (job panel, pre-check sheet). Not PANEL_BOX: its
           label rule would override the icon labels' font. */
        QFrame#{LIST_BOX} QLabel {{
            font-size: 12.5px;
            color: {t.text};
        }}
        QFrame#{LIST_BOX} QLabel#{PANEL_CAPTION} {{
            font-size: 11.5px;
            color: {t.text_3};
        }}
        QFrame#{LIST_BOX} QLabel#{PANEL_CAPTION}[tone="error"] {{
            color: {t.error};
        }}

        QListWidget#{IMAGE_LIST} {{
            {font}
            font-size: 13px;
            background-color: transparent;
            color: {t.text};
            border: none;
            outline: none;
        }}
        QListWidget#{IMAGE_LIST}::item {{
            padding: 7px 8px;
            border-radius: {RADIUS_SM}px;
        }}
        QListWidget#{IMAGE_LIST}::item:hover {{
            background-color: {t.hover};
        }}
        QListWidget#{IMAGE_LIST}::item:selected {{
            background-color: {t.bg};
            color: {t.text};
        }}
        QLabel#{IMAGE_PREVIEW}, QFrame#{IMAGE_PREVIEW} {{
            background-color: {t.paper};
            color: {t.paper_text};
        }}
        QLabel#{IMAGE_PREVIEW} {{
            border: 1px solid {t.paper_outline};
        }}

        /* The compile job panel: a raised white card over the workspace. */
        QFrame#{JOB_CARD} {{
            {font}
            background-color: {t.surface};
            border: 1px solid {t.line};
            border-radius: {RADIUS_MD}px;
        }}
        QFrame#{JOB_CARD} QLabel {{
            background-color: transparent;
            color: {t.text};
        }}
        QLabel#{JOB_TITLE} {{ font-size: 15px; font-weight: 500; }}
        QFrame#{JOB_CARD} QLabel#{JOB_SUB} {{ font-size: 13px; color: {t.text_2}; }}
        QLabel#{JOB_PCT} {{ font-size: 20px; font-weight: 500; }}
        QProgressBar#{JOB_BAR} {{
            min-height: 6px;
            max-height: 6px;
        }}

        /* The Log drawer: dark in both themes. */
        QFrame#{LOG_DRAWER} {{
            background-color: {t.log_bg};
            border-radius: {RADIUS_MD}px;
        }}
        QFrame#{LOG_HEAD} {{
            background-color: transparent;
            border: none;
            border-bottom: 1px solid {with_alpha(t.log_text, 0.1)};
        }}
        QFrame#{LOG_DRAWER} QLabel {{
            {font}
            font-size: 12px;
            color: {with_alpha(t.log_text, 0.55)};
            background-color: transparent;
        }}
        QFrame#{LOG_DRAWER} QLabel#{LOG_TITLE} {{ font-weight: 700; color: {t.log_text}; }}
        QPlainTextEdit#{LOG_TEXT} {{
            {mono}
            font-size: 11.5px;
            color: {t.log_text};
            background-color: transparent;
            border: none;
            padding: 0;
            selection-background-color: {with_alpha(t.log_text, 0.25)};
        }}
        QPlainTextEdit#{LOG_TEXT} QScrollBar:vertical {{
            background: transparent;
            width: 10px;
            margin: 0;
        }}
        QPlainTextEdit#{LOG_TEXT} QScrollBar::handle:vertical {{
            background: {with_alpha(t.log_text, 0.25)};
            border-radius: 4px;
            min-height: 24px;
        }}
        QPlainTextEdit#{LOG_TEXT} QScrollBar::handle:vertical:hover {{
            background: {with_alpha(t.log_text, 0.4)};
        }}
        QPushButton#{LOG_ACTION} {{
            {font}
            font-size: 12px;
            color: {with_alpha(t.log_text, 0.6)};
            background-color: transparent;
            border: none;
            padding: 4px 8px;
        }}
        QPushButton#{LOG_ACTION}:hover {{ color: {t.log_text}; }}
        QPushButton#{LOG_ERROR} {{
            {font}
            font-size: 12px;
            font-weight: 500;
            color: {t.on_solid};
            background-color: {t.error_solid};
            border: none;
            border-radius: {RADIUS_SM}px;
            padding: 4px 10px;
        }}

        /* Chat: the user's bubble, the model's text, tool cards, diff cards, notices. */
        QFrame#{CHAT_USER} {{
            background-color: {t.inverse};
            border-top-left-radius: 12px;
            border-top-right-radius: 12px;
            border-bottom-left-radius: 12px;
            border-bottom-right-radius: 3px;
        }}
        {text(f"QFrame#{CHAT_USER} QLabel", 13, t.on_inverse)}
        {text(f"QLabel#{CHAT_TEXT}", 13, t.text)}
        {text(f"QLabel#{CHAT_MODEL}", 10.5, t.text_3, None, mono)}
        {text(f"QLabel#{CHAT_TOOL_SUMMARY}", 12, t.text_2)}
        {text(f"QLabel#{CHAT_TOOL_NAME}", 11.5, t.text, 500, mono)}
        {text(f"QLabel#{CHAT_TOOL_BODY}", 11, t.text_2, None, mono)}
        QFrame#{CHAT_DIFF} {{
            background-color: transparent;
            border: 1px solid {t.line};
            border-radius: {RADIUS_MD}px;
        }}
        QFrame#{CHAT_DIFF} QLabel#{CHAT_DIFF_LINE} {{
            {mono}
            font-size: 11px;
            padding: 0 8px;
        }}
        QFrame#{CHAT_DIFF} QLabel#{CHAT_DIFF_LINE}[kind="add"] {{ background-color: {t.ok_bg}; color: {t.ok_fg}; }}
        QFrame#{CHAT_DIFF} QLabel#{CHAT_DIFF_LINE}[kind="del"] {{ background-color: {t.error_bg}; color: {t.error_fg}; }}
        QFrame#{CHAT_DIFF} QLabel#{CHAT_DIFF_LINE}[kind="ctx"] {{ color: {t.text_3}; }}
        QFrame#{CHAT_DIFF} QLabel#{CHAT_DIFF_LINE}[kind="gap"] {{ color: {t.text_4}; }}
        QFrame#{CHAT_DIFF}[state="rejected"] QLabel#{CHAT_DIFF_LINE}[kind="add"],
        QFrame#{CHAT_DIFF}[state="undone"] QLabel#{CHAT_DIFF_LINE}[kind="add"],
        QFrame#{CHAT_DIFF}[state="rejected"] QLabel#{CHAT_DIFF_LINE}[kind="del"],
        QFrame#{CHAT_DIFF}[state="undone"] QLabel#{CHAT_DIFF_LINE}[kind="del"] {{
            background-color: {t.bg};
            color: {t.text_4};
        }}
        QFrame#{CHAT_DIFF}[state="rejected"] QLabel#{CHAT_TOOL_NAME},
        QFrame#{CHAT_DIFF}[state="undone"] QLabel#{CHAT_TOOL_NAME} {{
            color: {t.text_4};
        }}
        QLabel#{CHAT_NOTICE} {{
            {font}
            font-size: 12px;
            padding: 8px 10px;
            border-radius: {RADIUS_MD}px;
            background-color: {t.bg};
            color: {t.text_2};
        }}
        QLabel#{CHAT_NOTICE}[tone="warning"] {{ background-color: {t.warning_bg}; color: {t.warning_fg}; }}
        QLabel#{CHAT_NOTICE}[tone="error"] {{ background-color: {t.error_bg}; color: {t.error_fg}; }}
        QPushButton#{CHAT_SUGGESTION} {{
            {font}
            font-size: 12.5px;
            text-align: left;
            color: {t.text};
            background-color: {t.bg};
            border: none;
            border-radius: {RADIUS_MD}px;
            padding: 6px 10px;
        }}
        QPushButton#{CHAT_SUGGESTION}:hover {{ background-color: {t.line}; }}
    """
