# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget
from slidemage import ai_review
from slidemage.project import ProjectContext
from slidemage.ui.workspace import wizard_portal as wizard


def test_small_edits_stay_quiet_complex_edits_trigger_once(monkeypatch):
    play = Mock()
    monkeypatch.setattr(wizard, 'play_wizard', play)
    w = SimpleNamespace()
    wizard.note_ai_edit(w, 'one.tex', 'hello', 'world')
    assert not play.called
    wizard.note_ai_edit(w, 'one.tex', '', '\n'.join(str(i) for i in range(12)))
    play.assert_called_once_with(w)
    wizard.note_ai_edit(w, 'two.tex', '', '\n'.join(str(i) for i in range(30)))
    assert play.call_count == 1


def test_multiple_files_qualify_but_unchanged_text_does_not(monkeypatch):
    play = Mock()
    monkeypatch.setattr(wizard, 'play_wizard', play)
    w = SimpleNamespace()
    wizard.note_ai_edit(w, 'one.tex', 'same', 'same')
    assert not hasattr(w, '_wizard_edits')
    wizard.note_ai_edit(w, 'one.tex', 'a', 'b')
    wizard.note_ai_edit(w, 'two.tex', 'a', 'b')
    assert play.call_count == 1


def test_old_review_records_do_not_replay_new_records_do(root, monkeypatch):
    ctx = ProjectContext.at(root)
    path = ctx.slides_dir / 'abc-EN-Hello-current.tex'
    before = path.read_text()
    after = before + '\n'.join(f'% change {i}' for i in range(12)) + '\n'
    path.write_text(after)
    ai_review.mark(ctx, path, 'edit', 'terminal hook', before=before)
    w = SimpleNamespace(project=ctx, centre=SimpleNamespace(slide_text=lambda p: p.read_text()))
    w._wizard_review = wizard.review_snapshot(w)
    play = Mock()
    monkeypatch.setattr(wizard, 'play_wizard', play)
    wizard.note_review_updates(w)
    assert not play.called
    next_text = after + '\n'.join(f'% next {i}' for i in range(12)) + '\n'
    path.write_text(next_text)
    ai_review.mark(ctx, path, 'edit', 'terminal hook', before=after)
    wizard.note_review_updates(w)
    play.assert_called_once_with(w)
    wizard.note_review_updates(w)
    assert play.call_count == 1


def test_overlay_replay_resize_clickthrough_cast_and_completion(qapp):
    w = QWidget()
    w.resize(1000, 650)
    w.show()
    a = wizard.play_wizard(w)
    assert a.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert wizard.play_wizard(w) is a
    w.resize(1100, 700)
    qapp.processEvents()
    assert a.geometry() == w.rect()
    cast, done = Mock(), Mock()
    a.cast.connect(cast)
    a.finished.connect(done)
    a.clock = SimpleNamespace(elapsed=lambda: 3600)
    a._tick(); a._tick()
    cast.assert_called_once()
    a.clock = SimpleNamespace(elapsed=lambda: 7000)
    a._tick()
    done.assert_called_once()
    assert not a.timer.isActive() and a.isHidden()
    w.close()


def test_transparent_artwork_and_all_animation_phases_render(qapp):
    w = QWidget()
    a = wizard.WizardPortal(w)
    assert a.poses[0].toImage().pixelColor(0, 0).alpha() == 0
    for t in (0, .6, 1.3, 2.4, 3.2, 3.6, 4.6, 6.8):
        image = QImage(1000, 650, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        a.paint_scene(painter, t)
        painter.end()
        assert image.pixelColor(0, 0).alpha() == 0
    w.close()
