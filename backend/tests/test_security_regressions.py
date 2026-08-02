"""Regression tests for fixed access-control holes.

Each test pins a specific vulnerability shut. They are hermetic — no live Mongo — because
they assert on the wiring (which dependency guards a route, which filter a query uses)
rather than on data.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _dependency_calls(route) -> set:
    """Every dependency callable a route resolves, including nested ones."""
    found, stack = set(), list(route.dependant.dependencies)
    while stack:
        dep = stack.pop()
        if dep.call is not None:
            found.add(dep.call)
        stack.extend(dep.dependencies)
    return found


class TestAdminIsSuperuserOnly:
    """Every /admin route leaked the whole user base (names, emails, proficiency, mood)
    to any authenticated learner, because it depended on get_current_user_id alone."""

    def test_every_admin_route_requires_superuser(self):
        from app.auth.jwt import require_superuser
        from app.routers import admin

        routes = [r for r in admin.router.routes if hasattr(r, "dependant")]
        assert routes, "no /admin routes found"

        # require_superuser itself depends on get_current_user_id, so asserting the
        # stronger guard is present is enough — authentication alone is not.
        for route in routes:
            assert require_superuser in _dependency_calls(route), (
                f"{route.path} is not superuser-gated"
            )

    def test_admin_learner_list_page_size_is_capped(self):
        """An uncapped limit turned one request into a full user-table dump."""
        from app.routers import admin

        route = next(
            r for r in admin.router.routes if getattr(r, "path", "") == "/learners"
        )
        limit = next(p for p in route.dependant.query_params if p.name == "limit")
        bounds = {
            type(c).__name__: getattr(c, "le", None) or getattr(c, "ge", None)
            for c in limit.field_info.metadata
        }
        assert bounds == {"Ge": 1, "Le": 100}, f"limit is not bounded 1..100: {bounds}"


class TestDoubtSessionsAreOwnerScoped:
    """Doubt transcripts were readable, and appendable, by id with no learner_id predicate."""

    @pytest.mark.asyncio
    async def test_read_filters_by_learner(self):
        from app.routers.doubts import get_session

        learners, doubts = MagicMock(), MagicMock()
        learners.return_value.find_one = AsyncMock(return_value={"id": "learner-A"})
        doubts.return_value.find_one = AsyncMock(return_value=None)

        with (
            patch("app.routers.doubts.col_learners", learners),
            patch("app.routers.doubts.col_doubts", doubts),
        ):
            result = await get_session("session-owned-by-B", user_id="user-A")

        query = doubts.return_value.find_one.call_args[0][0]
        assert query["learner_id"] == "learner-A", "read is not scoped to the caller"
        assert query["id"] == "session-owned-by-B"
        assert result == {"messages": []}

    @pytest.mark.asyncio
    async def test_read_without_a_learner_profile_returns_nothing(self):
        from app.routers.doubts import get_session

        learners, doubts = MagicMock(), MagicMock()
        learners.return_value.find_one = AsyncMock(return_value=None)
        doubts.return_value.find_one = AsyncMock(
            return_value={"id": "x", "messages": ["leak"]}
        )

        with (
            patch("app.routers.doubts.col_learners", learners),
            patch("app.routers.doubts.col_doubts", doubts),
        ):
            result = await get_session("any", user_id="ghost")

        assert result == {"messages": []}
        doubts.return_value.find_one.assert_not_called()

    def test_write_path_scopes_its_lookup_and_update(self):
        """The $push branch must match on learner_id too, or it appends to another
        learner's transcript when the client supplies their session id."""
        import inspect

        from app.routers import doubts

        source = inspect.getsource(doubts.stream_doubt)
        assert 'owned = {"id": session_id, "learner_id": learner["id"]}' in source
        assert "find_one(owned" in source
        assert (
            "update_one(\n                        owned," in source
            or "update_one(owned" in source
        )


class TestSuperuserSeeding:
    """A shipped default password seeded a role:superuser account in every environment
    that didn't override it — including production, where the APP_ENV guard was inert."""

    def test_no_default_credentials_in_source(self):
        from app.config import Settings

        fields = Settings.model_fields
        assert fields["SUPERUSER_EMAIL"].default == ""
        assert fields["SUPERUSER_PASSWORD"].default == ""

    @pytest.mark.asyncio
    async def test_seed_is_a_noop_without_env_credentials(self):
        from app.auth import jwt as jwt_mod

        users = MagicMock()
        users.return_value.find_one = AsyncMock()

        with (
            patch.object(jwt_mod.settings, "SUPERUSER_EMAIL", ""),
            patch.object(jwt_mod.settings, "SUPERUSER_PASSWORD", ""),
            patch("app.db.mongo.col_users", users),
        ):
            await jwt_mod.seed_superuser()

        users.return_value.find_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_existing_account_password_is_resynced_from_env(self):
        """This is what rotates a leaked superuser password on redeploy."""
        from app.auth import jwt as jwt_mod

        users = MagicMock()
        users.return_value.find_one = AsyncMock(
            return_value={"id": "u1", "role": "learner"}
        )
        users.return_value.update_one = AsyncMock()

        with (
            patch.object(jwt_mod.settings, "SUPERUSER_EMAIL", "root@example.com"),
            patch.object(
                jwt_mod.settings, "SUPERUSER_PASSWORD", "a-strong-new-password"
            ),
            patch("app.db.mongo.col_users", users),
        ):
            await jwt_mod.seed_superuser()

        update = users.return_value.update_one.call_args[0][1]["$set"]
        assert update["role"] == "superuser"
        assert jwt_mod.verify_password(
            "a-strong-new-password", update["hashed_password"]
        )
