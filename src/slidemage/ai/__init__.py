# SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
# SPDX-License-Identifier: GPL-3.0-or-later
"""AI provider layer: one way to talk to a local (Ollama) or cloud (Claude)
model. See providers.py for the protocol, ai_profile.py for choosing the route and model of a request,
resolver.py for turning that choice into a provider or backend."""
