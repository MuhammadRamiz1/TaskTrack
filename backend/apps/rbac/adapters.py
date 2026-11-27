"""How each model maps to scopes. One definition yields both the queryset filter and
the single-object check, so list filtering and object checks cannot diverge.

Modules register adapters for their models in ``AppConfig.ready``; the org module
registers the team/project resolvers once teams and projects exist.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from django.db.models import Model, Q

IdSet = set[Any]


@dataclass
class ScopeAdapter:
    company_attr: str = "company_id"
    own_q: Callable[[Any], Q] | None = None
    own_check: Callable[[Any, Model], bool] | None = None
    team_q: Callable[[IdSet], Q] | None = None
    team_ids_of: Callable[[Model], IdSet] | None = None
    project_q: Callable[[IdSet], Q] | None = None
    project_ids_of: Callable[[Model], IdSet] | None = None
    needs_distinct: bool = False


@dataclass
class _Registry:
    adapters: dict[type[Model], ScopeAdapter] = field(default_factory=dict)
    # (user, bound_team_id|None) -> team ids the grant covers
    team_resolver: Callable[[Any, Any], IdSet] = lambda user, bound: {bound} if bound else set()
    # (user, bound_team_id|None, bound_project_id|None) -> project ids the grant covers
    project_resolver: Callable[[Any, Any, Any], IdSet] = lambda user, team, project: {project} if project else set()


registry = _Registry()


def register(model: type[Model], adapter: ScopeAdapter) -> None:
    registry.adapters[model] = adapter


def adapter_for(model: type[Model]) -> ScopeAdapter:
    try:
        return registry.adapters[model]
    except KeyError as exc:
        raise LookupError(f"No ScopeAdapter registered for {model.__name__}") from exc


def set_resolvers(*, team: Callable | None = None, project: Callable | None = None) -> None:
    if team:
        registry.team_resolver = team
    if project:
        registry.project_resolver = project
