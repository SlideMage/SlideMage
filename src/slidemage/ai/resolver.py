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
from ..project import ProjectContext
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


def provider_for(ctx: ProjectContext, spec: str) -> ChatProvider:
    """The provider for a "<provider>:<model>" spec (a bare name is Ollama)."""
    name, model = app_settings.split_spec(spec)
    if name == "ollama":
        return OllamaProvider.for_project(ctx, model)
    if local_only(ctx):
        raise LocalOnlyError(
            "Local AI only is on, so cloud models are disabled "
            "(Settings -> AI models).")
    return AnthropicProvider.for_project(ctx, model)


def provider_for_task(ctx: ProjectContext, task: str) -> ChatProvider:
    """The provider configured for `task`; the Ollama default (no model
    chosen yet) when nothing is configured."""
    return provider_for(ctx, app_settings.default_model(ctx, task) or "ollama:")


# -- local only -----------------------------------------------------------

def project_local_only(ctx: ProjectContext) -> bool | None:
    """This project's override of the global switch; None = follow it."""
    ai = project.read_project_json(ctx.root).get("ai")
    value = ai.get("local_only") if isinstance(ai, dict) else None
    return value if isinstance(value, bool) else None


def set_project_local_only(ctx: ProjectContext, value: bool | None) -> None:
    data = project.read_project_json(ctx.root)
    ai = data.get("ai") if isinstance(data.get("ai"), dict) else {}
    if value is None:
        ai.pop("local_only", None)
    else:
        ai["local_only"] = value
    if ai:
        data["ai"] = ai
    else:
        data.pop("ai", None)
    project.write_project_json(ctx.root, data)


def global_local_only(ctx: ProjectContext) -> bool:
    return bool(app_settings.get(ctx, LOCAL_ONLY_SETTING_KEY))


def set_global_local_only(ctx: ProjectContext, value: bool) -> None:
    app_settings.set(ctx, LOCAL_ONLY_SETTING_KEY, value)


def local_only(ctx: ProjectContext) -> bool:
    override = project_local_only(ctx)
    return global_local_only(ctx) if override is None else override


# -- cloud models on offer --------------------------------------------------

def cloud_models(ctx: ProjectContext) -> list[str]:
    """Cloud models to list in the task pickers: none in local-only mode or
    without a key. The static list, so opening a dialog never waits on the
    network; Settings shows the live list."""
    if local_only(ctx) or credentials.get_api_key(ctx) is None:
        return []
    return list(ANTHROPIC_FALLBACK_MODELS)


# -- consent ------------------------------------------------------------

def cloud_consent_given(ctx: ProjectContext) -> bool:
    return bool(app_settings.get(ctx, CLOUD_CONSENT_SETTING_KEY))


def record_cloud_consent(ctx: ProjectContext) -> None:
    app_settings.set(ctx, CLOUD_CONSENT_SETTING_KEY, True)


def needs_cloud_consent(ctx: ProjectContext, provider: ChatProvider) -> bool:
    return not provider.is_local and not cloud_consent_given(ctx)
