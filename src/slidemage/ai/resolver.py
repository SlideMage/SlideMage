"""Which provider and model answers an AI task, and whether it may be a
cloud one (2026-10-09, UI redesign step 2).

A task's choice is one string, ``ollama:<model>`` or ``anthropic:<model>``
(app_settings.default_model(); an older bare model name reads as Ollama).
provider_for() turns such a spec into a provider object.

"Local AI only": a global switch in app_settings.json, overridable per
project in the project's ``.slidemage/project.json`` under
``"ai": {"local_only": true|false}`` (tracked with the project, like the
"compat" state, so a project that must keep its content off the cloud says
so for everyone who opens it; absent means "follow the global switch").
When it is on, provider_for() *raises* LocalOnlyError for a cloud spec
rather than quietly substituting some Ollama model: the user chose that
model, a silent swap would answer with something they did not pick, and
the pickers do not list cloud models in this mode, so the error only
surfaces for a stale selection.

Consent: the first cloud request in a project must be confirmed once. The
flag lives in app_settings.json, which already sits inside the project
folder, so it is per project; the prompt itself is the UI's job
(ui/ai_models.confirm_cloud_request).
"""
from __future__ import annotations

from .. import app_settings, project
from ..deck_scan import PROJECT_ROOT
from . import credentials
from .providers import (
    ANTHROPIC_FALLBACK_MODELS,
    AnthropicProvider,
    ChatProvider,
    OllamaProvider,
    ProviderError,
)

LOCAL_ONLY_SETTING_KEY = "local_ai_only"
CLOUD_CONSENT_SETTING_KEY = "cloud_consent"


class LocalOnlyError(ProviderError):
    """A cloud model was requested while "Local AI only" is on."""


def provider_for(spec: str) -> ChatProvider:
    """The provider for a "<provider>:<model>" spec (a bare name is Ollama)."""
    name, model = app_settings.split_spec(spec)
    if name == "ollama":
        return OllamaProvider(model)
    if local_only():
        raise LocalOnlyError(
            "Local AI only is on, so cloud models are disabled "
            "(Settings -> AI models).")
    return AnthropicProvider(model)


def provider_for_task(task: str) -> ChatProvider:
    """The provider configured for `task`; the Ollama default (no model
    chosen yet) when nothing is configured."""
    return provider_for(app_settings.default_model(task) or "ollama:")


# -- local only -----------------------------------------------------------

def project_local_only() -> bool | None:
    """This project's override of the global switch; None = follow it."""
    ai = project.read_project_json(PROJECT_ROOT).get("ai")
    value = ai.get("local_only") if isinstance(ai, dict) else None
    return value if isinstance(value, bool) else None


def set_project_local_only(value: bool | None) -> None:
    data = project.read_project_json(PROJECT_ROOT)
    ai = data.get("ai") if isinstance(data.get("ai"), dict) else {}
    if value is None:
        ai.pop("local_only", None)
    else:
        ai["local_only"] = value
    if ai:
        data["ai"] = ai
    else:
        data.pop("ai", None)
    project.write_project_json(PROJECT_ROOT, data)


def global_local_only() -> bool:
    return bool(app_settings.get(LOCAL_ONLY_SETTING_KEY))


def set_global_local_only(value: bool) -> None:
    app_settings.set(LOCAL_ONLY_SETTING_KEY, value)


def local_only() -> bool:
    override = project_local_only()
    return global_local_only() if override is None else override


# -- cloud models on offer --------------------------------------------------

def cloud_models() -> list[str]:
    """Cloud models to list in the task pickers: none in local-only mode or
    without a key. The static list, so opening a dialog never waits on the
    network; Settings shows the live list."""
    if local_only() or credentials.get_api_key() is None:
        return []
    return list(ANTHROPIC_FALLBACK_MODELS)


# -- consent ------------------------------------------------------------

def cloud_consent_given() -> bool:
    return bool(app_settings.get(CLOUD_CONSENT_SETTING_KEY))


def record_cloud_consent() -> None:
    app_settings.set(CLOUD_CONSENT_SETTING_KEY, True)


def needs_cloud_consent(provider: ChatProvider) -> bool:
    return not provider.is_local and not cloud_consent_given()
