# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Transparent Qt wizard overlay. No video codecs or extra runtime dependencies.

Call play_wizard(window) on the GUI thread; connect overlay.cast to a visual change.
"""
from __future__ import annotations

import difflib
import math
import time
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget


def ease(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3 - 2 * value)


def color(value, alpha=1.0):
    result = QColor(value)
    result.setAlphaF(max(0.0, min(1.0, alpha)))
    return result


class WizardPortal(QWidget):
    cast = Signal()
    finished = Signal()
    duration = 6.8
    cast_time = 3.55

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        asset = Path(__file__).parents[2] / "assets" / "wizard-poses.png"
        if not asset.is_file():
            asset = Path(__file__).with_name("wizard-poses.png")
        sheet = QPixmap(str(asset))
        if sheet.isNull():
            raise FileNotFoundError("Wizard animation asset wizard-poses.png is missing")
        # The casting wands extend slightly past nominal cell boundaries.
        # Use the transparent gutters so every star stays with its wizard.
        width, height = sheet.width(), sheet.height()
        self.poses = [sheet.copy(int(left * width), int(top * height),
                                 int((right - left) * width), height // 2)
                      for left, right, top in ((0, 1/3, 0), (1/3, 2/3, 0), (2/3, 1, 0),
                                               (0, 540/1536, .5), (540/1536, 1080/1536, .5),
                                               (1080/1536, 1, .5))]
        self.seconds = 0.0
        self._cast = False
        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        parent.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, event):
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        return super().eventFilter(obj, event)

    def play(self):
        self.seconds = 0.0
        self._cast = False
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self.clock.start()
        self.timer.start()
        self.update()

    def stop(self):
        self.timer.stop()
        self.hide()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def _tick(self):
        self.seconds = self.clock.elapsed() / 1000
        if self.seconds >= self.cast_time and not self._cast:
            self._cast = True
            self.cast.emit()
        if self.seconds >= self.duration:
            self.stop()
            self.finished.emit()
        else:
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        scale = min(self.width() / 1000, self.height() / 650)
        painter.translate((self.width() - 1000 * scale) / 2, (self.height() - 650 * scale) / 2)
        painter.scale(scale, scale)
        self.paint_scene(painter, self.seconds)
        painter.end()

    def paint_scene(self, p, t):
        fade = 1 - ease((t - 5.65) / 1.15)
        p.setOpacity(fade)
        opening = ease(t / .85) * (1 - ease((t - 2.3) / .8))
        # Portal depth and concentric rotating embers.
        if opening > .001:
            p.save()
            p.translate(255, 353)
            p.scale(opening, 1)
            glow = QRadialGradient(QPointF(0, 0), 210)
            glow.setColorAt(0, color("#230647", .9))
            glow.setColorAt(.57, color("#4c1388", .88))
            glow.setColorAt(.77, color("#bb69ff", .35))
            glow.setColorAt(1, color("#9b43fa", 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.save()
            p.scale(.62, 1)
            p.drawEllipse(QRectF(-210, -210, 420, 420))
            p.restore()
            p.setBrush(Qt.BrushStyle.NoBrush)
            for width, alpha in ((16, .07), (8, .16), (2, .8)):
                p.setPen(QPen(color("#bd82ff", alpha), width))
                p.drawEllipse(QRectF(-88, -172, 176, 344))
            for n in range(110):
                angle = n * math.tau / 110 + t * (1.3 if n % 2 else -.8)
                x, y = 88 * math.cos(angle), 172 * math.sin(angle)
                p.setPen(QPen(color("#f9c768" if n % 3 else "#c19aff", .65 + .3 * math.sin(n) ** 2), 2 + n % 3))
                p.drawLine(QPointF(x, y), QPointF(x + 8 * math.cos(angle + .8), y + 8 * math.sin(angle + .8)))
            p.restore()

        progress = ease((t - .65) / 1.8)
        x = 155 + progress * 165
        y = 220 - math.sin(progress * math.pi * 6) * 5 * (1 - progress)
        pose = int(max(0, t - .65) * 5) % 2 if t < 2.45 else (2 if t < 3.05 else 3 if t < 3.4 else 4 if t < 4.35 else 5)
        visibility = ease((t - .6) / .55)
        p.save()
        p.setOpacity(fade * visibility)
        # Reveal from the portal's plane as the wizard steps out.
        p.setClipRect(QRectF(205, 85, 790, 510))
        sprite = self.poses[pose]
        p.drawPixmap(QRectF(x, y, 330 * sprite.width() / (sprite.height()), 330),
                     sprite, QRectF(sprite.rect()))
        p.restore()

        # Curved wand sweep, then a stream of golden magic into the target.
        if 3.05 < t < 4.8:
            trail = ease((t - 3.05) / .5)
            opacity = 1 - ease((t - 4) / .8)
            for n in range(54):
                u = n / 53
                if u > trail:
                    continue
                px = 635 + u * 125
                py = 333 - math.sin(u * math.pi) * 80 + u * 22
                self._spark(p, px, py, (3 + 3 * math.sin(n * 2) ** 2) * opacity, fade * opacity)
            self._spark(p, 635 + trail * 125, 333 - math.sin(trail * math.pi) * 80 + trail * 22, 14 * opacity, fade)

        if 3.55 < t < 5.5:
            burst = (t - 3.55) / 1.95
            for n in range(46):
                angle = n * 2.39996
                radius = 170 * burst * (.4 + (n % 7) / 9)
                self._spark(p, 760 + math.cos(angle) * radius, 355 + math.sin(angle) * radius,
                            (2 + n % 4) * (1 - burst), fade * (1 - burst))

    @staticmethod
    def _spark(p, x, y, radius, opacity):
        p.save()
        p.setOpacity(opacity)
        gradient = QRadialGradient(QPointF(x, y), max(.1, radius * 3))
        gradient.setColorAt(0, color("#fffbe0"))
        gradient.setColorAt(.25, color("#ffd475", .9))
        gradient.setColorAt(1, color("#f9a847", 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(gradient)
        p.drawEllipse(QPointF(x, y), radius * 3, radius * 3)
        p.setPen(QPen(color("#fff7ce"), 1.3))
        p.drawLine(QPointF(x - radius, y), QPointF(x + radius, y))
        p.drawLine(QPointF(x, y - radius), QPointF(x, y + radius))
        p.restore()


def play_wizard(window):
    """Replay one owned overlay; connect its cast signal to a real UI change."""
    overlay = getattr(window, "_wizard_portal", None)
    if overlay is None:
        overlay = WizardPortal(window)
        window._wizard_portal = overlay
    overlay.play()
    return overlay


def changed_lines(before, after):
    """Count changed source lines, excluding unchanged diff context."""
    return sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in
               difflib.SequenceMatcher(None, before.splitlines(), after.splitlines(), autojunk=False).get_opcodes()
               if tag != "equal")


def note_ai_edit(window, path, before, after):
    """GUI thread, successful edits only. Complex = 12 changed lines or 2 files in 8s.

    A 20s cooldown avoids replaying for every file in a large batch.
    """
    if before == after:
        return
    now = time.monotonic()
    entries = [(stamp, name, count) for stamp, name, count in getattr(window, "_wizard_edits", [])
               if now - stamp < 8]
    entries.append((now, str(path), changed_lines(before, after)))
    window._wizard_edits = entries
    complex_edit = sum(count for _, _, count in entries) >= 12 or len({name for _, name, _ in entries}) >= 2
    if complex_edit and now - getattr(window, "_wizard_last_play", -1000) >= 20:
        window._wizard_last_play = now
        window._wizard_edits = []
        try:
            play_wizard(window)
        except FileNotFoundError:
            pass  # Optional artwork must never interrupt a successful AI edit.


def review_snapshot(window):
    from ... import ai_review
    return {key: (entry.get("since"), entry.get("text_hash"))
            for key, entry in ai_review.unreviewed(window.project).items()}


def note_review_updates(window):
    """Observe the shared provenance store, including terminal hook edits."""
    from ... import ai_review
    current = review_snapshot(window)
    previous = getattr(window, "_wizard_review", current)
    window._wizard_review = current
    for key, signature in current.items():
        if previous.get(key) == signature:
            continue
        path = window.project.root / key
        before = ai_review.last_before(window.project, path)
        if before is None:
            continue
        try:
            after = window.centre.slide_text(path)
        except (OSError, UnicodeError):
            continue
        note_ai_edit(window, path, before, after)

