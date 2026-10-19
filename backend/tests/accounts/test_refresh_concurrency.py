"""Two requests refresh with the same token at the same moment.

The session row is locked (SELECT ... FOR UPDATE), so exactly one rotation
wins; the other sees an already-rotated token and is treated as reuse.
"""

import threading
from typing import Any

import pytest
from django.db import connections

from apps.accounts import services
from apps.accounts.services import ClientInfo, InvalidRefreshToken, SessionTokens

pytestmark = pytest.mark.usefixtures("committed_db")


def test_concurrent_refresh_with_one_token_has_one_winner() -> None:
    tokens = services.signup(
        email=f"race-{threading.get_ident()}-{id(object())}@example.com",
        password="correct horse battery staple",
        full_name="Race Condition",
        business_name="Race Co",
        client=ClientInfo(),
    )
    barrier = threading.Barrier(2)
    results: list[Any] = []

    def refresh() -> None:
        try:
            barrier.wait(timeout=10)
            results.append(services.refresh(tokens.refresh_token, ClientInfo()))
        except Exception as exc:  # collected and asserted below
            results.append(exc)
        finally:
            connections.close_all()  # each thread has its own connection

    threads = [threading.Thread(target=refresh) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    winners = [r for r in results if isinstance(r, SessionTokens)]
    losers = [r for r in results if isinstance(r, InvalidRefreshToken)]
    assert len(winners) == 1, results
    assert len(losers) == 1, results
    # strict reuse detection: the loser's attempt ended the whole family
    assert not services.session_is_live(tokens.session_id)
