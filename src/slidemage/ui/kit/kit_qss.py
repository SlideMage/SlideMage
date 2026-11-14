# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
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
    SPACE,
    FONT_ICONS,
    FONT_MONO,
    FONT_SANS,
    RADIUS_MD,
    RADIUS_PILL,
    RADIUS_SM,
    RADIUS_XS,
    TYPE,
    VIEWS,
    Tokens,
    pill,
    with_alpha,
)

CARD = "kitCard"
SEGMENTED = "kitSegmented"
CHIP = "kitChip"
BADGE = "kitBadge"
PLAIN_LIST = "kitPlainList"     # rows that bring their own look
TOOL_WINDOW = "kitToolWindow"     # a separate window of a plugin
LABEL_BODY = "kitLabelBody"
LABEL_SECONDARY = "kitLabelSecondary"
LABEL_MONO = "kitLabelMono"
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
MENU_HEADER = "kitMenuHeader"   # a section title in a menu of the menu bar
MENU_SEPARATOR = "kitMenuSeparator"
MENU_COLUMN = "kitMenuColumn"
MENU_FOOTER = "kitMenuFooter"
MENU_NOTE = "kitMenuNote"
MENU_SWATCH = "kitMenuSwatch"
TOAST = "kitToast"
TOAST_ACTION = "kitToastAction"
SHEET = "kitSheet"
SHEET_TITLE = "kitSheetTitle"
SHEET_SECTION = "kitSheetSection"   # a section's heading in a sheet tab
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
# The tabs above the views (ui/workspace/centre_tabs.py).
TAB_STRIP = "kitTabStrip"
TAB = "kitTab"
TAB_LABEL = "kitTabLabel"
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

# The AI switch (the assistant card's first row) and its popovers (ui/workspace/ai_switch.py, ai_popups.py, ai_setup.py).
AI_SWITCH = "kitAiSwitch"
AI_SWITCH_STATE = "kitAiSwitchState"
AI_POPUP_TITLE = "kitAiPopupTitle"
AI_POPUP_TEXT = "kitAiPopupText"
AI_POPUP_LINK = "kitAiPopupLink"
AI_SETUP_HEAD = "kitAiSetupHead"
AI_SETUP_CELL = "kitAiSetupCell"
# The assistant card's header, the running-task pill and the Claude Code setup card (ui/workspace/assistant*.py).
ASSISTANT_TITLE = "kitAssistantTitle"
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

CHIP_TONES = ("neutral", "muted", "info", "warning", "error", "ok", "ok_text")


def _chip_colors(t: Tokens, tone: str) -> tuple[str, str]:
    """(background, text) of a chip tone."""
    return {
        "neutral": (t.bg, t.text),
        "muted": (t.bg, t.text_2),
        "info": (t.info_bg, t.info_fg),
        "warning": (t.warning_bg, t.warning_fg),
        "error": (t.error_bg, t.error_fg),
        "ok": (t.ok_bg, t.ok_fg),
        "ok_text": ("transparent", t.ok),       # green text only: a background says there is something to do
    }[tone]


def build_kit_qss(t: Tokens, icons: Mapping[str, str]) -> str:
    """`icons` maps the names in KIT_ICONS to image files, for the arrows and ticks of the controls."""
    font = f'font-family: "{FONT_SANS}";'
    mono = f'font-family: "{FONT_MONO}";'

    # Nominal heights used by the round indicators, chips and count badges.
    RADIO_HEIGHT = 18
    CHIP_HEIGHT = 18
    BADGE_HEIGHT = 20
    SEGMENT_BADGE_HEIGHT = 14

    def text(selector: str, size: int, color: str, weight: int | None = None, family: str = font) -> str:
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
            font-size: {TYPE.body}px;
            background-color: {t.surface};
            color: {t.text};
            border: 1px solid {t.line};
            border-radius: {RADIUS_SM}px;
            padding: {SPACE.xs}px {SPACE.lg}px;
        }}
        QPushButton:hover {{
            background-color: {t.hover};
        }}
        QPushButton:disabled {{
            color: {t.text_4};
        }}
        QToolTip {{
            {font}
            font-size: {TYPE.small}px;
            background-color: {t.inverse};
            color: {t.on_inverse};
            border: none;
            padding: {SPACE.xs}px {SPACE.md}px;
        }}
        QMenu {{
            {font}
            font-size: {TYPE.body}px;
            background-color: {t.surface};
            color: {t.text};
            border: 1px solid {t.line};
            border-radius: {RADIUS_SM}px;
            padding: {SPACE.xs}px;
        }}
        QMenu::item {{
            /* Leave room for the combo arrow and retain native control height. */
            padding: 5px 24px 5px {SPACE.xl}px;
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
        QMenuBar {{
            {font}
            font-size: {TYPE.body}px;
            background-color: {t.surface};
            color: {t.text};
            border-bottom: 1px solid {t.line};
            padding: {SPACE.s_2xs}px {SPACE.md}px;
        }}
        QMenuBar::item {{
            background: transparent;
            padding: {SPACE.xs}px {SPACE.lg}px;
            border-radius: {RADIUS_SM}px;
        }}
        QMenuBar::item:selected {{
            background-color: {t.hover};
        }}
        QMenuBar::item:pressed {{
            background-color: {t.info_bg};
            color: {t.info_fg};
        }}
        QLabel#{MENU_HEADER} {{
            {font}
            font-size: {TYPE.micro}px;
            font-weight: 500;
            color: {t.text_3};
            padding: {SPACE.sm}px {SPACE.xl}px {SPACE.s_2xs}px {SPACE.xl}px;
        }}

        /* Form controls, everywhere: a field on the page color with a line
           under it (prototype v3), a ring when it has the focus. */
        QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QComboBox {{
            {font}
            font-size: {TYPE.control}px;
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
        QDateTimeEdit:focus, QComboBox:focus, QComboBox:on {{
            border-color: {t.info};
        }}
        QLineEdit[edited="true"] {{
            border-left: 3px solid {t.info};
            font-weight: 600;
        }}
        QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled, QSpinBox:disabled,
        QDoubleSpinBox:disabled, QDateTimeEdit:disabled, QComboBox:disabled {{
            color: {t.text_4};
            border-bottom-color: {t.line};
        }}
        QComboBox, QDateTimeEdit {{
            padding-right: 28px;
        }}
        QComboBox::drop-down, QDateTimeEdit::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: center right;
            width: 26px;
            border: none;
        }}
        QComboBox::down-arrow, QDateTimeEdit::down-arrow {{
            image: url({icons["chevron_down"]});
            width: 18px;
            height: 18px;
        }}
        QComboBox QAbstractItemView {{
            {font}
            font-size: {TYPE.body}px;
            background-color: {t.surface};
            color: {t.text};
            border: 1px solid {t.line};
            border-radius: {RADIUS_SM}px;
            padding: {SPACE.xs}px;
            outline: none;
            selection-background-color: {t.hover};
            selection-color: {t.text};
        }}
        QComboBox QAbstractItemView::item {{
            min-height: 22px;
            padding: {SPACE.s_2xs}px {SPACE.md}px;
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
            font-size: {TYPE.body}px;
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
            border-radius: {RADIUS_XS}px;
        }}
        QRadioButton::indicator {{
            border-radius: {pill(RADIO_HEIGHT):g}px;
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
            font-size: {TYPE.body}px;
            background-color: {t.bg};
            color: {t.text};
            border: none;
            border-radius: {RADIUS_MD}px;
            padding: {SPACE.xs}px;
            outline: none;
        }}
        QListWidget::item {{
            padding: 5px {SPACE.md}px;
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
            border-radius: {RADIUS_XS}px;
            text-align: center;
        }}
        QProgressBar::chunk {{
            background-color: {t.inverse};
            border-radius: {RADIUS_XS}px;
        }}
        /* A bar that prints its percent (the update download's QProgressDialog)
           cannot use the strong inverse fill: it is the text colour, so the
           percent vanished once the fill reached it. A translucent wash of
           the text colour stays readable under the text on both parts. */
        QProgressDialog QProgressBar {{
            color: {t.text};
        }}
        QProgressDialog QProgressBar::chunk {{
            background-color: {with_alpha(t.text, 0.3)};
        }}
        QSplitter#{SURFACE}::handle:horizontal {{
            background: {t.line};
            margin: 0 4px;
        }}
        QSplitter#{SURFACE}::handle:horizontal:hover, QSplitter#{SURFACE}::handle:horizontal:pressed {{
            background: {t.text_4};
        }}
        QSplitter#{SURFACE}::handle:vertical {{
            background: transparent;
        }}
        QSplitter#{SURFACE}::handle:vertical:hover, QSplitter#{SURFACE}::handle:vertical:pressed {{
            background: {t.text_4};
            margin: 5px 4px;
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
            border-radius: {RADIUS_SM}px;
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
            font-size: {TYPE.small}px;
            font-weight: 500;
            background-color: transparent;
            color: {t.text_2};
            border: none;
            border-bottom: 1px solid transparent;
            border-radius: {RADIUS_SM}px;
            padding: 5px {SPACE.lg}px;
        }}
        QPushButton[kitSegment="true"][mono="true"] {{
            font-family: "Roboto Mono";
            font-size: {TYPE.micro}px;
            font-weight: 600;
            padding: 5px {SPACE.md}px;
        }}
        QPushButton[kitSegment="true"][badge="true"] {{
            padding-right: 22px;
        }}
        QLabel#{BADGE} {{
            {font}
            font-size: {TYPE.micro}px;
            font-weight: 700;
            color: {t.on_inverse};
            background-color: {t.inverse};
            border-radius: {pill(BADGE_HEIGHT):g}px;
            padding: 0 {SPACE.sm}px;
            min-height: {BADGE_HEIGHT}px;
            min-width: 8px;
        }}
        QLabel#{BADGE}[tone="info"] {{ color: {t.info_fg}; background-color: {t.info_bg}; }}
        QLabel#{BADGE}[tone="error"] {{ color: {t.on_solid}; background-color: {t.error_solid}; }}
        {text(f"QLabel#{LABEL_BODY}", TYPE.body, t.text)}
        {text(f"QLabel#{LABEL_SECONDARY}", TYPE.body, t.text_2)}
        {text(f"QLabel#{LABEL_MONO}", TYPE.small, t.text_2, family=mono)}
        QLabel#{SEGMENT_BADGE} {{
            {font}
            font-size: {TYPE.micro}px;
            font-weight: 700;
            color: {t.on_solid};
            background-color: {t.error_solid};
            border-radius: {pill(SEGMENT_BADGE_HEIGHT):g}px;
            padding: 0 {SPACE.xs}px;
            min-width: 8px;
            min-height: {SEGMENT_BADGE_HEIGHT}px;
        }}
        QPushButton[kitSegment="true"]:hover {{
            color: {t.text};
            background-color: transparent;
        }}
        QPushButton[kitSegment="true"]:disabled, QPushButton[kitSegment="true"][unavailable="true"] {{
            color: {t.text_4};
            background-color: transparent;
        }}
        QPushButton[kitSegment="true"][unavailable="true"]:hover {{
            color: {t.text_3};
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
        QPushButton[kitSegment="true"][mono="true"]:focus {{ padding: 3px {SPACE.sm}px; }}
        QPushButton[kitSegment="true"][badge="true"]:focus {{ padding-right: 20px; }}
        QPushButton[kitSegment="true"][withIcon="true"]:focus {{ padding-left: 28px; }}
        QLabel#{ICON}[segment="off"] {{ color: {t.text_2}; }}
        QLabel#{ICON}[segment="on"] {{ color: {t.text}; }}
        QLabel#{ICON}[segment="cloud"] {{ color: {t.on_solid}; }}

        /* Fonts are set on the container and reach the labels through Qt's
           font propagation; a QSS font rule on the label itself would also
           override the icon labels' Material Icons font. */
        /* Half the chip's height at most: Qt draws square corners for a radius beyond that (RADIUS_PILL would). */
        QFrame#{CHIP} {{
            {font}
            font-size: {TYPE.small}px;
            border-radius: {pill(CHIP_HEIGHT):g}px;
        }}
        QFrame#{CHIP}[mono="true"] QLabel {{ font-family: "{FONT_MONO}"; font-size: {TYPE.micro}px; }}
        QFrame#{CHIP}[mono="true"] QLabel#{ICON} {{ font-family: "{FONT_ICONS}"; font-size: {TYPE.control}px; }}
        {chips}
        QFrame#{CHIP}[pressable="true"] {{ border: 2px solid transparent; }}
        QFrame#{CHIP}[pressable="true"]:focus {{ border-color: {t.focus}; }}

        /* A chip that switches on and off; on, it takes the colors of its view. */
        QPushButton#{TOGGLE_CHIP} {{
            {font}
            font-size: {TYPE.small}px;
            font-weight: 500;
            background-color: transparent;
            color: {t.text_3};
            border: 1px solid {t.line};
            border-radius: {RADIUS_PILL}px;
            padding: {SPACE.xs}px {SPACE.xl}px;
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
        QPushButton#{TOGGLE_CHIP}:focus {{ border: 2px solid {t.focus}; padding: 3px 11px; }}

        /* Buttons. "primary" is the dark/inverse fill, "secondary" a bordered
           surface button, "ghost" a flat one. */
        QPushButton[kind] {{
            {font}
            font-size: {TYPE.body}px;
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
            font-size: {TYPE.body}px;
            padding: {SPACE.xs}px 9px;
        }}
        QPushButton[kind]:disabled {{
            color: {t.text_4};
            background-color: {t.bg};
            border-color: {t.line};
        }}
        QPushButton[kind]:focus {{ border: 2px solid {t.focus}; padding: {SPACE.sm}px 13px; }}
        QPushButton[kind][compact="true"]:focus {{ padding: 3px {SPACE.md}px; }}

        QFrame#{SPLIT} {{
            background-color: {t.inverse};
            border-radius: {RADIUS_SM}px;
        }}
        QFrame#{SPLIT} QPushButton {{
            {font}
            font-size: {TYPE.body}px;
            font-weight: 500;
            background-color: transparent;
            color: {t.on_inverse};
            border: none;
            border-radius: 0;
            padding: 7px {SPACE.xl}px;
        }}
        QFrame#{SPLIT} QPushButton:hover {{
            background-color: rgba(0,0,0,0.12);
            color: {t.on_inverse};
        }}
        /* The caret is an icon glyph: it needs the icon font back. */
        QFrame#{SPLIT} QPushButton#{SPLIT_CARET} {{
            font-family: "{FONT_ICONS}";
            font-size: {TYPE.title}px;
            font-weight: 400;
            padding: 5px 7px;
        }}
        QFrame#{SPLIT} QPushButton:focus {{ border: 2px solid {t.focus}; padding: 5px {SPACE.lg}px; }}
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
        QToolButton#{ICON_BUTTON}[faint="true"] {{ color: {with_alpha(t.text_4, 0.55)}; }}
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
            font-size: {TYPE.body}px;
            background-color: transparent;
            border: none;
            outline: none;
        }}
        QFrame#{MENU} QListWidget::item {{
            padding: {SPACE.sm}px {SPACE.md}px;
            border-radius: {RADIUS_SM}px;
            color: {t.text};
        }}
        QFrame#{MENU} QListWidget::item:selected {{
            background-color: {t.hover};
            color: {t.text};
        }}
        QWidget#{MENU_ROW} {{
            {font}
            font-size: {TYPE.body}px;
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
            font-size: {TYPE.small}px;
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
            font-size: {TYPE.micro}px;
            font-weight: 500;
            color: {t.text_3};
            padding: {SPACE.sm}px {SPACE.lg}px {SPACE.s_2xs}px {SPACE.lg}px;
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
            padding: {SPACE.sm}px {SPACE.xs}px {SPACE.s_2xs}px {SPACE.xs}px;
        }}
        QFrame#{MENU}[columns="true"] QWidget#{MENU_ROW} {{ font-size: {TYPE.body}px; }}
        QFrame#{MENU}[columns="true"] QWidget#{MENU_ROW} QLabel#{MENU_META} {{
            {mono}
            font-size: {TYPE.micro}px;
        }}
        {text(f'QFrame#{MENU}[columns="true"] QLabel#{MENU_HEADER}', TYPE.body, t.text_2, 500)}
        QFrame#{MENU}[columns="true"] QLabel#{MENU_HEADER} {{ padding: {SPACE.md}px {SPACE.lg}px 3px {SPACE.lg}px; }}
        QFrame#{MENU_FOOTER} QWidget#{MENU_ROW} QLabel#{MENU_TEXT} {{ font-weight: 500; }}
        {text(f"QLabel#{MENU_NOTE}", TYPE.small, t.text_3)}
        QLabel#{MENU_NOTE} {{ padding: 0 {SPACE.md}px; }}

        QFrame#{MENU_SWATCH} {{
            border: 1px solid {t.line};
            border-radius: {RADIUS_XS}px;
        }}

        QFrame#{TOAST} {{
            {font}
            font-size: {TYPE.body}px;
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
            font-size: {TYPE.body}px;
            font-weight: 500;
            background-color: {with_alpha(t.on_inverse, 0.14)};
            color: {t.on_inverse};
            border: none;
            border-radius: {RADIUS_SM}px;
            padding: {SPACE.xs}px {SPACE.lg}px;
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
            background-color: {with_alpha(t.scrim, 0.4)};
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
            font-size: {TYPE.heading}px;
            color: {t.text};
            background-color: transparent;
            border: none;
            padding: 0;
        }}
        QFrame#{PALETTE_FOOT} {{
            border-top: 1px solid {t.line};
        }}
        {text(f"QFrame#{PALETTE_FOOT} QLabel", TYPE.small, t.text_3)}
        {text(f"QLabel#{PALETTE_KEYS}", TYPE.micro, t.text_3, None, mono)}

        QDialog#{SHEET} {{
            background-color: {t.surface};
        }}
        QDialog#{SHEET} QStackedWidget, QDialog#{SHEET} QTabBar {{
            background-color: transparent;
        }}
        {text(f"QLabel#{SHEET_TITLE}", TYPE.title, t.text, 500)}
        {text(f"QLabel#{SHEET_SECTION}", TYPE.heading, t.text, 500)}
        /* The read-only route badge under a dialog's title: a grey pill, amber on Cloud. */
        QFrame#{MODE_BADGE} {{ background-color: {t.bg}; border-radius: {RADIUS_PILL}px; }}
        QFrame#{MODE_BADGE}[cloud="true"] {{ background-color: {t.cloud_bg}; }}
        {text(f"QLabel#{MODE_BADGE_TEXT}", TYPE.small, t.text_2, 500)}
        QFrame#{MODE_BADGE}[cloud="true"] QLabel {{ color: {t.cloud_fg}; }}
        {text(f"QLabel#{FIELD_LABEL}", TYPE.body, t.text_2, 500)}
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
            font-size: {TYPE.micro}px;
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
            font-size: {TYPE.body}px;
            font-weight: 500;
            background-color: transparent;
            color: {t.text_3};
            border: none;
            border-bottom: 2px solid transparent;
            padding: {SPACE.md}px 14px;
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
            font-size: {TYPE.control}px;
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
        {text(f"QLabel#{TOPBAR_LABEL}", TYPE.small, t.text_3)}

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
        {text(f"QLabel#{AI_SWITCH_STATE}", TYPE.small, t.text_2, 600)}
        QLabel#{AI_SWITCH_STATE}[cloud="true"] {{ color: {t.cloud_fg}; }}
        QFrame#{AI_SWITCH} QToolButton#{ICON_BUTTON}[cloud="true"] {{ color: {t.cloud_fg}; }}
        QFrame#{AI_SWITCH}[cloud="true"] QFrame#{SEGMENTED} {{ background-color: {with_alpha(t.text, 0.06)}; }}

        /* The popovers of the switch (they are kitMenu frames with 16px padding). */
        {text(f"QLabel#{AI_POPUP_TITLE}", TYPE.control, t.text, 600)}
        {text(f"QLabel#{AI_POPUP_TEXT}", TYPE.body, t.text_2)}
        QPushButton#{AI_POPUP_LINK} {{
            {font} font-size: {TYPE.body}px; color: {t.text_2}; text-decoration: underline;
            background-color: transparent; border: 2px solid transparent; border-radius: {RADIUS_SM}px; padding: 0 {SPACE.s_2xs}px;
        }}
        QPushButton#{AI_POPUP_LINK}:hover {{ color: {t.text}; }}
        QPushButton#{AI_POPUP_LINK}:focus {{ border-color: {t.focus}; }}
        {text(f"QLabel#{AI_SETUP_HEAD}", TYPE.body, t.text_3, 600)}
        QLabel#{AI_SETUP_HEAD}[active="true"] {{ color: {t.text}; }}
        QFrame#{MENU} QFrame#{LIST_BOX} {{ border-radius: {RADIUS_SM}px; }}
        QComboBox#{AI_SETUP_CELL} {{
            {mono}
            font-size: {TYPE.small}px;
            min-height: 20px;
            padding: 3px {SPACE.sm}px;
            padding-right: 22px;
        }}
        QComboBox#{AI_SETUP_CELL}[active="false"] {{ color: {t.text_4}; }}
        QComboBox#{AI_SETUP_CELL}::drop-down {{ width: 20px; }}
        QLabel#{AI_SETUP_CELL} {{
            {mono}
            font-size: {TYPE.small}px;
            color: {t.text_3};
        }}
        {text(f"QLabel#{TOPBAR_SAVE}", TYPE.small, t.text_3)}

        /* The assistant header: the route's title (amber in Cloud), its model, and the target of the scope. */
        {text(f"QLabel#{ASSISTANT_TITLE}", TYPE.control, t.text, 600)}
        QLabel#{ASSISTANT_TITLE}[cloud="true"] {{ color: {t.cloud_fg}; }}
        {text(f"QLabel#{ASSISTANT_TARGET}", TYPE.body, t.text_2)}
        QFrame#{TASK_PILL} {{ background-color: {t.bg}; border-radius: {RADIUS_SM}px; }}
        {text(f"QFrame#{TASK_PILL} QLabel", TYPE.body, t.text)}
        QFrame#{TASK_CARD} {{ border: 1px solid {t.line}; border-radius: {RADIUS_MD}px; }}
        {text(f"QLabel#{TASK_TITLE}", TYPE.heading, t.text, 600)}
        {text(f"QLabel#{TASK_ROUTE}", TYPE.small, t.local_fg, None, mono)}
        QLabel#{TASK_ROUTE}[cloud="true"] {{ color: {t.cloud_text}; }}
        {text(f"QLabel#{TASK_STATE}", TYPE.control, t.text)}
        QLabel#{TASK_STATE}[tone="ok"] {{ color: {t.ok_fg}; }}
        QLabel#{TASK_STATE}[tone="warning"] {{ color: {t.cloud_text}; }}
        QLabel#{TASK_STATE}[tone="error"] {{ color: {t.error}; }}
        QLabel#{TASK_STATE}[tone="muted"] {{ color: {t.text_2}; }}
        {text(f"QLabel#{TASK_ELAPSED}", TYPE.small, t.text_3, None, mono)}
        {text(f"QLabel#{TASK_STEP}", TYPE.small, t.text_3)}
        QFrame#{CLOUD_CARD} {{
            background-color: {t.cloud_bg};
            border: 1px solid {t.cloud_border};
            border-radius: {RADIUS_MD}px;
        }}
        QFrame#{CLOUD_CARD} QLabel {{ background-color: transparent; color: {t.cloud_fg}; }}
        QFrame#{CLOUD_CARD} QLabel#{ICON} {{ color: {t.cloud_solid}; }}
        {text(f"QFrame#{CLOUD_CARD} QLabel#{ASSISTANT_TITLE}", TYPE.control, t.cloud_fg, 600)}

        /* Slide list: the find box is a white field on the grey page, the
           tree draws its own rows (slide_tree.py). */
        QLineEdit#{SLIDES_FIND} {{
            {font}
            font-size: {TYPE.control}px;
            background-color: {t.surface};
            color: {t.text};
            border: none;
            border-radius: {RADIUS_SM}px;
            padding: 0 {SPACE.xl}px;
            min-height: 40px;
        }}
        QLineEdit#{SLIDES_RENAME} {{
            {font}
            font-size: {TYPE.small}px;
            font-weight: 600;
            background-color: {t.surface};
            color: {t.text};
            border: 1.5px solid {t.info};
            border-radius: {RADIUS_SM}px;
            padding: 0 {SPACE.md}px;
        }}
        QTreeWidget#{SLIDES_TREE} {{
            background-color: transparent;
            border: none;
            outline: none;
        }}
        QLabel#{SLIDES_NOTE} {{
            {font}
            font-size: {TYPE.body}px;
            color: {t.text_3};
            padding: {SPACE.s_2xl}px {SPACE.md}px;
        }}
        {text(f"QLabel#{SLIDES_BULK_LABEL}", TYPE.body, t.text, 500)}

        /* Centre column: containers are transparent on the white card, so a
           plain QFrame doesn't take the page color of the app-wide rule. */
        #{SURFACE} {{
            background-color: transparent;
        }}
        QFrame#{SOURCE_BAR}, QFrame#{AI_PANEL} {{
            background-color: transparent;
            border-bottom: 1px solid {t.line};
        }}
        /* The centre's tabs: a hairline under the strip; the tab shown has the inverse line the sheet tabs have. */
        QFrame#{TAB_STRIP} {{
            background-color: transparent;
            border-bottom: 1px solid {t.line};
        }}
        QFrame#{TAB} {{
            background-color: transparent;
            border: none;
            border-right: 1px solid {t.line};
            border-top: 3px solid transparent;
            border-bottom: 2px solid transparent;
        }}
        /* A deck's tabs carry its stripe along the top edge (tab-contexts.md E7), one of six hues in the order the decks were opened. */
        {"".join(f'QFrame#{TAB}[deckColour="{i}"] {{ border-top: 3px solid {c}; }}' + chr(10) for i, c in enumerate((*t.steps[1:6], t.warning)))}
        QFrame#{TAB}:hover {{ background-color: {t.hover}; }}
        QFrame#{TAB}:focus {{ border-bottom: 2px solid {t.focus}; }}
        QFrame#{TAB}[active="true"] {{ border-bottom: 2px solid {t.inverse}; }}
        /* The tab shown gets the usual SlideMage blue fill, the same one the selected deck version (Instructor) uses. */
        QFrame#{TAB}[active="true"] {{ background-color: {t.view_instructor}; }}
        {text(f"QLabel#{TAB_LABEL}", TYPE.body, t.text_3, 500)}
        QFrame#{TAB}:hover QLabel#{TAB_LABEL} {{ color: {t.text}; }}
        QFrame#{TAB}[active="true"] QLabel#{TAB_LABEL} {{ color: {t.on_solid}; }}
        QPlainTextEdit#{SOURCE} {{
            {mono}
            font-size: {TYPE.body}px;
            background-color: {t.surface};
            color: {t.text};
            border: none;
            padding: 0;
        }}
        QFrame#{AI_ROW}, QFrame#{DETAILS_PANEL}, QFrame#{PANEL_BOX}, QFrame#{LIST_BOX}, QFrame#{CHAT_TOOL} {{
            background-color: {t.bg};
            border-radius: {RADIUS_MD}px;
        }}
        {text(f"QFrame#{AI_ROW} QLabel", TYPE.body, t.text)}
        QFrame#{AI_ROW} QLabel#{DIFF_OLD}, QFrame#{AI_ROW} QLabel#{DIFF_NEW} {{
            {mono}
            font-size: {TYPE.small}px;
            padding: {SPACE.s_2xs}px {SPACE.sm}px;
            border-radius: {RADIUS_XS}px;
        }}
        QFrame#{AI_ROW} QLabel#{DIFF_OLD} {{
            background-color: {t.error_bg};
            color: {t.error_fg};
        }}
        QFrame#{AI_ROW} QLabel#{DIFF_NEW} {{
            background-color: {t.ok_bg};
            color: {t.ok_fg};
        }}
        {text(f"QLabel#{SOURCE_NOTE}", TYPE.small, t.text_3)}
        {text(f"QLabel#{SOURCE_FILE_NAME}", TYPE.small, t.text, None, mono)}

        {text(f"QLabel#{PREVIEW_TITLE}", TYPE.body, t.text, 600)}
        {text(f"QLabel#{PREVIEW_ID}", TYPE.small, t.text_2, 500, mono)}

        {text(f"QLabel#{DETAILS_LABEL}", TYPE.body, t.text_3)}
        {text(f"QLabel#{DETAILS_VALUE}", TYPE.body, t.text)}
        {text(f"QLabel#{DETAILS_TITLE}", TYPE.title, t.text, 500)}
        {text(f"QFrame#{DETAILS_PANEL} QLabel", TYPE.body, t.text)}
        {text(f"QLabel#{DETAILS_HEAD}", TYPE.body, t.text, 600)}
    
        /* Side panels: the picker is a grey pill; a panel's content sits in grey boxes
           whose rows are separated by hairlines. */
        QFrame#{PANEL_PICKER} {{
            background-color: {t.bg};
            {font}
            font-size: {TYPE.body}px;
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
        {text(f"QFrame#{PANEL_BOX} QLabel", TYPE.body, t.text)}
        QFrame#{PANEL_BOX} QLabel#{DETAILS_LABEL} {{
            color: {t.text_3};
        }}
        QFrame#{PANEL_BOX} QLabel#{PANEL_MONO}, QFrame#{LIST_BOX} QLabel#{PANEL_MONO},
        QDialog#{SHEET} QLabel#{PANEL_MONO} {{
            {mono}
            font-size: {TYPE.small}px;
        }}
        {text(f"QFrame#{PANEL_BOX} QLabel#{PANEL_CAPTION}, QLabel#{PANEL_CAPTION}", TYPE.small, t.text_3)}
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
            font-size: {TYPE.small}px;
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
            font-size: {TYPE.micro}px;
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
        QListWidget#{PLAIN_LIST}, QListWidget#{PLAIN_LIST} > QWidget {{
            background-color: transparent;
            border: none;
        }}
        QListWidget#{PLAIN_LIST}::item, QListWidget#{PLAIN_LIST}::item:hover, QListWidget#{PLAIN_LIST}::item:selected {{
            background-color: transparent;
            padding: 0;
        }}
        QFrame#{ROW_BUTTON}[selected="true"] {{
            background-color: {t.info_bg};
        }}
        QFrame#{ROW_BUTTON}[selected="true"] QLabel#{PANEL_CAPTION} {{
            color: {t.text_2};
        }}
        QFrame#{ROW_BUTTON}[selected="true"] QLabel#{BADGE}[tone="info"] {{
            color: {t.surface};
            background-color: {t.info};
        }}
        QLabel#{ROW_NAME} {{
            {font}
            font-size: {TYPE.control}px;
            font-weight: 500;
        }}

        /* A grey box of rows (job panel, pre-check sheet). Not PANEL_BOX: its
           label rule would override the icon labels' font. */
        QFrame#{LIST_BOX} QLabel {{
            font-size: {TYPE.body}px;
            color: {t.text};
        }}
        QFrame#{LIST_BOX} QLabel#{PANEL_CAPTION} {{
            font-size: {TYPE.small}px;
            color: {t.text_3};
        }}
        QFrame#{LIST_BOX} QLabel#{PANEL_CAPTION}[tone="error"] {{
            color: {t.error};
        }}

        QListWidget#{IMAGE_LIST} {{
            {font}
            font-size: {TYPE.body}px;
            background-color: transparent;
            color: {t.text};
            border: none;
            outline: none;
        }}
        QListWidget#{IMAGE_LIST}::item {{
            padding: 7px {SPACE.md}px;
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
        QLabel#{JOB_TITLE} {{ font-size: {TYPE.heading}px; font-weight: 500; }}
        QFrame#{JOB_CARD} QLabel#{JOB_SUB} {{ font-size: {TYPE.body}px; color: {t.text_2}; }}
        QLabel#{JOB_PCT} {{ font-size: {TYPE.display}px; font-weight: 500; }}
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
            font-size: {TYPE.small}px;
            color: {with_alpha(t.log_text, 0.55)};
            background-color: transparent;
        }}
        QFrame#{LOG_DRAWER} QLabel#{LOG_TITLE} {{ font-weight: 700; color: {t.log_text}; }}
        QPlainTextEdit#{LOG_TEXT} {{
            {mono}
            font-size: {TYPE.small}px;
            color: {t.log_text};
            background-color: transparent;
            border: none;
            padding: 0;
            selection-background-color: {with_alpha(t.log_text, 0.25)};
        }}
        QPlainTextEdit#{LOG_TEXT} QScrollBar:vertical {{
            background: {t.log_bg};   /* not transparent: the strip is painted by the edit's frame, which is light */
            width: 10px;
            margin: 0;
        }}
        QPlainTextEdit#{LOG_TEXT} QScrollBar::add-page:vertical, QPlainTextEdit#{LOG_TEXT} QScrollBar::sub-page:vertical {{
            background: {t.log_bg};
        }}
        QPlainTextEdit#{LOG_TEXT} QScrollBar::handle:vertical {{
            background: {with_alpha(t.log_text, 0.25)};
            border-radius: {RADIUS_SM}px;
            min-height: 24px;
        }}
        QPlainTextEdit#{LOG_TEXT} QScrollBar::handle:vertical:hover {{
            background: {with_alpha(t.log_text, 0.4)};
        }}
        QPushButton#{LOG_ACTION} {{
            {font}
            font-size: {TYPE.small}px;
            color: {with_alpha(t.log_text, 0.6)};
            background-color: transparent;
            border: none;
            padding: {SPACE.xs}px {SPACE.md}px;
        }}
        QPushButton#{LOG_ACTION}:hover {{ color: {t.log_text}; }}
        QPushButton#{LOG_ERROR} {{
            {font}
            font-size: {TYPE.small}px;
            font-weight: 500;
            color: {t.on_solid};
            background-color: {t.error_solid};
            border: none;
            border-radius: {RADIUS_SM}px;
            padding: {SPACE.xs}px {SPACE.lg}px;
        }}

        /* Chat: the user's bubble, the model's text, tool cards, diff cards, notices. */
        QFrame#{CHAT_USER} {{
            background-color: {t.inverse};
            border-top-left-radius: {RADIUS_MD}px;
            border-top-right-radius: {RADIUS_MD}px;
            border-bottom-left-radius: {RADIUS_MD}px;
            border-bottom-right-radius: {RADIUS_XS}px;
        }}
        {text(f"QFrame#{CHAT_USER} QLabel", TYPE.body, t.on_inverse)}
        {text(f"QLabel#{CHAT_TEXT}", TYPE.body, t.text)}
        {text(f"QLabel#{CHAT_MODEL}", TYPE.micro, t.text_3, None, mono)}
        {text(f"QLabel#{CHAT_TOOL_SUMMARY}", TYPE.small, t.text_2)}
        {text(f"QLabel#{CHAT_TOOL_NAME}", TYPE.small, t.text, 500, mono)}
        {text(f"QLabel#{CHAT_TOOL_BODY}", TYPE.micro, t.text_2, None, mono)}
        QFrame#{CHAT_DIFF} {{
            background-color: transparent;
            border: 1px solid {t.line};
            border-radius: {RADIUS_MD}px;
        }}
        QFrame#{CHAT_DIFF} QLabel#{CHAT_DIFF_LINE} {{
            {mono}
            font-size: {TYPE.micro}px;
            padding: 0 {SPACE.md}px;
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
            font-size: {TYPE.small}px;
            padding: {SPACE.md}px {SPACE.lg}px;
            border-radius: {RADIUS_MD}px;
            background-color: {t.bg};
            color: {t.text_2};
        }}
        QLabel#{CHAT_NOTICE}[tone="warning"] {{ background-color: {t.warning_bg}; color: {t.warning_fg}; }}
        QLabel#{CHAT_NOTICE}[tone="error"] {{ background-color: {t.error_bg}; color: {t.error_fg}; }}
        QPushButton#{CHAT_SUGGESTION} {{
            {font}
            font-size: {TYPE.body}px;
            text-align: left;
            color: {t.text};
            background-color: {t.bg};
            border: none;
            border-radius: {RADIUS_MD}px;
            padding: {SPACE.sm}px {SPACE.lg}px;
        }}
        QPushButton#{CHAT_SUGGESTION}:hover {{ background-color: {t.line}; }}
    """
