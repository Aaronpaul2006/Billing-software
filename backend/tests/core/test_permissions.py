"""The role/action matrix, cell by cell, as written in docs/01-architecture.md §3."""

import pytest

from apps.core.permissions import ACTIONS, ALL_ROLES, can

# Copied from the architecture document's table (✓ = allowed), in role order
# OWNER, ADMIN, ACCOUNTANT, SITE_ENGINEER, VIEWER.
MATRIX = {
    "tenant.settings": "✓✓···",
    "members.manage": "✓✓···",
    "masters.edit": "✓✓✓··",
    "boq.edit": "✓✓✓✓·",
    "documents.draft": "✓✓✓✓·",
    "documents.issue": "✓✓✓··",
    "payments.record": "✓✓✓··",
    "expenses.record": "✓✓✓✓·",
    "reports.view": "✓✓✓·✓",
    "audit.view": "✓✓···",
    "tenant.ownership": "✓····",
    "tenant.read": "✓✓✓✓✓",
}


def test_matrix_covers_every_action() -> None:
    assert set(MATRIX) == set(ACTIONS)


@pytest.mark.parametrize("action", sorted(MATRIX))
def test_role_matrix(action: str) -> None:
    for role, cell in zip(ALL_ROLES, MATRIX[action], strict=True):
        assert can(role, action) is (cell == "✓"), f"{role} / {action}"


def test_unknown_action_is_an_error_not_a_denial() -> None:
    with pytest.raises(ValueError, match="unknown action"):
        can("OWNER", "documents.isue")
