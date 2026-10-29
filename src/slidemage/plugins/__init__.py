# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugins: optional features that live outside SlideMage, in their own folder, and are loaded at start.

manifest reads a plugin's plugin.toml, loader finds, checks and imports plugins, registry records what a plugin
registers. The interface a plugin sees is slidemage.plugin_api, never anything in here."""
