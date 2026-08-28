"""Project deterministic UI actions from persisted failure/recovery facts."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProjectErrorActionsQueryV1:
    run_status: str
    recovery_allowed_resolutions: tuple[str, ...] = ()
    reauth_required: bool = False


@dataclass(frozen=True, slots=True)
class ProjectErrorActionsResultV1:
    action_ids: tuple[str, ...]


class ProjectErrorActionsHandler:
    def __call__(self, query: ProjectErrorActionsQueryV1) -> ProjectErrorActionsResultV1:
        actions: list[str] = []
        if query.reauth_required:
            actions.append("REAUTHENTICATE")
        if query.run_status == "RECOVERY_REQUIRED":
            actions.extend(query.recovery_allowed_resolutions)
        if query.run_status not in {"COMPLETED", "CANCELLED", "FAILED"}:
            actions.append("CANCEL")
        return ProjectErrorActionsResultV1(tuple(dict.fromkeys(actions)))


__all__ = [
    "ProjectErrorActionsHandler",
    "ProjectErrorActionsQueryV1",
    "ProjectErrorActionsResultV1",
]
