"""Qt glue shared by every AI model picker (2026-10-09, UI redesign step 2):
filling a picker with local and cloud models, turning the selection into a
provider, and the one-time privacy confirmation before the first cloud
request in a project. One helper set so the five pickers behave alike.

Each picker item's data is the model spec ("ollama:qwen3",
"anthropic:claude-sonnet-5-5"); local items show the plain model name,
cloud items add " (cloud)".
"""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QMessageBox, QWidget

from . import app_settings
from .ai import resolver
from .ai.providers import ChatProvider, ProviderError


def fill_model_combo(
    combo: QComboBox, task: str, local_models: list[str], empty_text: str,
    fallback_local: str = "",
) -> bool:
    """(Re)fill `combo` with `local_models` plus the cloud models on offer
    (none in local-only mode or without an API key) and preselect the
    task's default from Settings -> "AI models", else `fallback_local` when
    it is installed. With nothing to offer it shows `empty_text` disabled
    and returns False."""
    combo.clear()
    for model in local_models:
        combo.addItem(model, f"ollama:{model}")
    for model in resolver.cloud_models():
        combo.addItem(f"{model} (cloud)", f"anthropic:{model}")
    usable = combo.count() > 0
    combo.setEnabled(usable)
    if not usable:
        combo.addItem(empty_text, "")
        return False
    index = combo.findData(app_settings.default_model(task))
    if index == -1 and fallback_local:
        index = combo.findData(f"ollama:{fallback_local}")
    if index != -1:
        combo.setCurrentIndex(index)
    return True


def confirm_cloud_request(parent: QWidget, provider: ChatProvider, what: str) -> bool:
    """True when a request to `provider` may go ahead. A local provider
    always may; the first cloud request in a project asks once, naming
    `what` is sent, and remembers a yes (resolver.record_cloud_consent)."""
    if not resolver.needs_cloud_consent(provider):
        return True
    answer = QMessageBox.question(
        parent, "Send to the cloud?",
        f"This request goes to a cloud model ({provider.label}) and sends {what} "
        "to Anthropic. Nothing is sent unless you agree.\n\n"
        "You are asked this once per project; \"Local AI only\" in Settings "
        "turns cloud models off.",
    )
    if answer != QMessageBox.StandardButton.Yes:
        return False
    resolver.record_cloud_consent()
    return True


def provider_from_combo(parent: QWidget, combo: QComboBox, what: str) -> ChatProvider | None:
    """The provider for the picker's selection, or None after telling the user why not (no
    model, local-only, or consent declined)."""
    return _confirmed_provider(parent, combo.currentData(), what, "No AI model is available. "
                               "Install an Ollama model or add an API key in Settings.")


def _confirmed_provider(parent: QWidget, spec: str, what: str, missing: str) -> ChatProvider | None:
    if not spec:
        QMessageBox.critical(parent, "AI model", missing)
        return None
    try:
        provider = resolver.provider_for(spec)
    except ProviderError as exc:
        QMessageBox.critical(parent, "AI model", str(exc))
        return None
    return provider if confirm_cloud_request(parent, provider, what) else None


def provider_for_task(parent: QWidget, task: str, what: str) -> ChatProvider | None:
    """The provider Settings -> "AI models" names for `task` (a MODEL_SETTINGS key), for a place
    with no picker of its own; None after telling the user why not (no model chosen, local-only,
    or consent declined)."""
    return _confirmed_provider(parent, app_settings.default_model(task), what,
                               "No AI model is chosen for this task. Choose one under Settings -> AI models.")
