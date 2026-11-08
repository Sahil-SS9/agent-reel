"""Maintainer review fixes: redaction is opt-in, and only the current profile is read.

Teknium's review of the pinned build (29/10/26) asked for three things: the key lookup
order, the local redaction model becoming opt-in rather than a silent default, and
profile discovery defaulting to the current profile. The key-order behaviour is covered in
``test_action_grammar.py``; this file covers the other two.
"""

from __future__ import annotations

import argparse

import pytest

from canon.llm import NullLLM


# --------------------------------------------------------------------------- #
# Fix 2 - the local redaction model is opt-in
# --------------------------------------------------------------------------- #


def _plan_args(argv: list[str]) -> argparse.Namespace:
    from adapters.hermes.reel_cli import register_cli

    parser = argparse.ArgumentParser(prog="hermes reel")
    register_cli(parser)
    return parser.parse_args(argv)


def test_plan_without_an_llm_url_is_the_deterministic_path():
    """No --llm-url means no route at all: `hermes reel plan` must not acquire one."""
    args = _plan_args(["plan", "--dry-run"])
    assert args.llm_url is None
    assert isinstance(_client_for(args), NullLLM)


def test_plan_opts_in_only_when_the_operator_names_the_route():
    args = _plan_args(["plan", "--dry-run", "--llm-url", "http://127.0.0.1:8091/v1"])
    client = _client_for(args)
    assert not isinstance(client, NullLLM)
    assert client.base_url == "http://127.0.0.1:8091/v1"


def _client_for(args: argparse.Namespace):
    from adapters.hermes.reel_cli import redaction_client

    return redaction_client(args.llm_url)


def test_the_cli_wires_the_opt_in_flags_into_the_run(tmp_path, monkeypatch):
    """The flags on the real command end up on the run: opt-in means nothing is on by default."""
    from adapters.hermes import pipeline as pl
    from adapters.hermes import reel_cli

    seen: list = []

    class Ctx:
        llm = object()

    monkeypatch.setattr(reel_cli, "_CTX", Ctx())
    monkeypatch.setattr(pl, "run_pipeline", lambda config: seen.append(config) or pl.PipelineResult())

    # Default run: no route, one profile.
    assert reel_cli.reel_command(
        _plan_args(["plan", "--dry-run", "--data-dir", str(tmp_path / "a")])
    ) == 0
    # Opted in: both flags travel.
    assert reel_cli.reel_command(
        _plan_args(
            [
                "plan",
                "--dry-run",
                "--data-dir",
                str(tmp_path / "b"),
                "--all-profiles",
                "--llm-url",
                "http://127.0.0.1:8091/v1",
            ]
        )
    ) == 0
    assert len(seen) == 2
    plain, opted_in = seen
    assert plain.all_profiles is False
    assert isinstance(plain.llm, NullLLM)
    assert opted_in.all_profiles is True
    assert not isinstance(opted_in.llm, NullLLM)
    assert opted_in.llm.base_url == "http://127.0.0.1:8091/v1"


@pytest.fixture()
def _no_local_route(monkeypatch):
    """Any attempt to build a model client inside the pipeline fails the calling test."""
    from adapters.hermes import pipeline as pl

    built: list[str] = []

    class Boom:
        def __init__(self, *args, **kwargs):
            built.append(str(kwargs.get("base_url") or "model-client"))
            raise AssertionError("a model route was built without being asked for")

        @classmethod
        def local(cls, *args, **kwargs):
            built.append("local")
            raise AssertionError("the local model route was built without being asked for")

    monkeypatch.setattr(pl, "OpenAICompatLLMClient", Boom)
    return built


def test_the_pipeline_never_builds_a_model_route_on_the_callers_behalf(
    hermes_env, tmp_path, monkeypatch, _no_local_route
):
    """``use_model`` with no client supplied is the deterministic path, not a silent local
    endpoint: the old default reached 127.0.0.1:8091 without being asked."""
    from adapters.hermes import pipeline as pl
    from conftest import StubWriter

    gates: list[object] = []

    class RecordingGate:
        def __init__(self, *args, **kwargs):
            gates.append(self)

    monkeypatch.setattr(pl, "ModelEntityGate", RecordingGate)
    config = pl.PipelineConfig(
        data_dir=tmp_path / "data",
        days=28,
        use_model=True,
        snapshot_root=tmp_path / "snapshots",
        state_dir=tmp_path / "state",
        writer=StubWriter(),
        min_strip_panels=3,
    )
    pl.run_pipeline(config)
    # No local route, and no model redaction pass either: redaction stayed deterministic.
    assert _no_local_route == []
    assert gates == []


# --------------------------------------------------------------------------- #
# Fix 3 - only the current profile is read unless the fleet is requested
# --------------------------------------------------------------------------- #


def test_a_named_profile_home_reads_that_profile_only(synthetic_home, monkeypatch):
    """A profile home is the profile: its own state.db, and no sibling directory."""
    from adapters.hermes.history import HermesHistorySource
    from adapters.hermes.paths import HermesPaths

    monkeypatch.delenv("HERMES_PROFILE", raising=False)
    home = synthetic_home / "profiles" / "beta"
    paths = HermesPaths.resolve(home)
    assert paths.current_profile_name() == "beta"
    source = HermesHistorySource(root=home)
    assert source._selected_profiles() == []
    # Sessions come from that profile's store, and only that store.
    owned = {event.profile for event in source.events(_window(), ["session"]) if event.profile}
    assert owned == {"beta"}, owned


def test_a_root_home_reads_the_default_profile_and_not_its_siblings(synthetic_home, monkeypatch):
    from adapters.hermes.history import HermesHistorySource
    from adapters.hermes.paths import HermesPaths

    monkeypatch.delenv("HERMES_PROFILE", raising=False)
    assert HermesPaths.resolve(synthetic_home).current_profile_name() == "default"
    source = HermesHistorySource(root=synthetic_home)
    assert source._selected_profiles() == []
    # The siblings' session stores are never opened. The fleet-wide kanban.db still
    # attributes tasks to the profiles that ran them, which is not a cross-profile read.
    sessions = list(source.events(_window(), ["session"]))
    assert {event.profile for event in sessions if event.profile} == {"default"}
    assert not [event for event in sessions if event.id.startswith("synthetic-alpha-")]


def test_the_fleet_is_read_only_when_asked(synthetic_home, monkeypatch):
    from adapters.hermes.history import HermesHistorySource

    monkeypatch.delenv("HERMES_PROFILE", raising=False)
    source = HermesHistorySource(root=synthetic_home, all_profiles=True)
    assert {store.name for store in source._selected_profiles()} == {
        "alpha",
        "beta",
        "gamma",
        "delta",
    }


def test_hermes_profile_names_the_current_profile(synthetic_home, monkeypatch):
    from adapters.hermes.history import HermesHistorySource

    monkeypatch.setenv("HERMES_PROFILE", "gamma")
    source = HermesHistorySource(root=synthetic_home)
    assert [store.name for store in source._selected_profiles()] == ["gamma"]


def _window():
    from datetime import datetime, timezone

    from canon.source import Window

    now = datetime.now(tz=timezone.utc).timestamp()
    return Window(since=now - 40 * 86400)
