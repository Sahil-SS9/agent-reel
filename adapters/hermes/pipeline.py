"""The M1 pipeline: ingest -> redact -> beats -> arcs -> canon -> episode plan -> IR.

Runs outside the live plugin (two-phase rule, HANDOFF §2): the CLI reads history
read-only, runs the gate and the story engine, and writes artifacts to a data
directory. No image step in M1 - script only.

Design notes that matter for the gate:

* **Deterministic pass on everything.** Every event is gated deterministically,
  no model involved.
* **Model pass where it pays.** The name vocabulary is learned once for the whole
  window (batched, cached) and applied everywhere; span-level detail is only run
  on the story subset that actually feeds the episode. Both are recorded, so a
  reader knows which events were deep-gated.
* **Fail closed.** A model error or a residue hit quarantines the event. Nothing
  that failed the gate reaches beats.
* **Cache.** Every model call goes through ``canon.cache``, so a second run over
  the same window is byte-identical.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Iterable, Sequence

from canon.brief import build_brief
from canon.selection import select_stories
from canon.threads import beats_by_thread
from canon.arcs import build_brief_arc
from canon.arcs import build_arcs
from canon.beats import Beat, beats_from_events
from canon.cache import ModelCache
from canon.aliases import AliasBook, apply_to_ir, masks_in
from canon.canon import Canon, build_canon
from canon.caption import compose_caption, trim_caption
from canon.casting import build_cast_map, summarise as summarise_cast
from canon.facts import build_facts, facts_text
from canon.episode import (
    EpisodeRefused,
    EpisodeIR,
    LLMDialogueWriter,
    TemplateDialogueWriter,
    plan_episode,
    usable_anchor_count,
    validate_ir,
)
from canon.events import Event
from canon.gate import GatedEvent
from canon.grounding import ClaimGate
from canon.llm import CachedLLM, LLMClient, NullLLM
from canon.redact import DeterministicRedactor, ModelEntityGate, RedactionGate
from canon.source import Window
from canon.threads import build_threads
from canon.titling import write_title

from adapters.hermes import leakscan
from adapters.hermes.evidence import EvidenceLeak, write_json, write_text
from adapters.hermes.history import HermesHistorySource
from adapters.hermes.llm import FallbackLLM, OpenAICompatLLMClient
from adapters.hermes.redact_source import public_rules, rules_from_snapshot
from adapters.hermes.snapshot import SnapshotStore, build_snapshot

#: People and tools that may appear by name in the comic.
DEFAULT_ALLOWLIST = (
    "Sahil",
    "Kensei",
    "KENSEI",
    "Hermes",
    "Claude",
    "Codex",
    "GitHub",
    "Discord",
    "Telegram",
    "Python",
    "SQLite",
    "Linux",
    "Turbofit",
    "Severian",
    "ComfyUI",
)

DEFAULT_HERO = "Sahil"
MAX_DEEP_EVENTS = 200
MAX_TEXT_CHARS = 2000
MAX_TEXT_EVENTS = 20000

#: Which events are worth fetching text for, cheapest-story-first. ``tool.call``
#: is absent on purpose: the raw ``tool_calls`` JSON is not story material, and a
#: week contains tens of thousands of them.
TEXT_PRIORITY: dict[str, int] = {
    "message.user": 0,
    "kanban.task.created": 1,
    "kanban.comment": 1,
    "session.started": 2,
    "kanban.task.status": 3,
    "cron.run.finished": 3,
    "kanban.task.finished": 4,
    "kanban.run.finished": 5,
    "memory.fact": 6,
    "message.assistant": 7,
    "message.tool_result": 8,
    "message.meta": 9,
}


@dataclass
class PipelineConfig:
    data_dir: Path
    days: float = 7.0
    since: float | None = None
    until: float | None = None
    profiles: tuple[str, ...] | None = None
    format: str = "strip"
    season: int = 1
    number: int = 1
    use_model: bool = False
    allowlist: tuple[str, ...] = DEFAULT_ALLOWLIST
    hero: str = DEFAULT_HERO
    max_deep_events: int = MAX_DEEP_EVENTS
    max_text_chars: int = MAX_TEXT_CHARS
    max_text_events: int = MAX_TEXT_EVENTS
    max_vocabulary: int = 400
    privacy: str = "private"
    episodes: int = 1
    writer_llm: Any = None
    writer: Any = None
    max_writer_calls: int = 150
    snapshot_root: Path | None = None
    #: Where the private memory snapshot lives. Never the evidence folder (M1-F4).
    state_dir: Path | None = None
    llm: LLMClient | None = None


@dataclass
class PipelineResult:
    events_ingested: int = 0
    events_with_text: int = 0
    gated: int = 0
    quarantined: int = 0
    beats: list[Beat] = field(default_factory=list)
    arc_count: int = 0
    ir: EpisodeIR | None = None
    canon: Canon | None = None
    gate_report: dict[str, Any] = field(default_factory=dict)
    cache_stats: dict[str, int] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    grounding: dict[str, Any] = field(default_factory=dict)
    threads: int = 0
    quarantine_rate: float = 0.0
    title: str = ""
    title_source: str = ""
    cast: list[dict[str, Any]] = field(default_factory=list)
    episodes: list[dict[str, Any]] = field(default_factory=list)
    llm_usage: dict[str, Any] = field(default_factory=dict)
    stories: list[dict[str, Any]] = field(default_factory=list)
    skipped_stories: list[dict[str, str]] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    artifacts: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.ir and not self.problems)


# --------------------------------------------------------------------------- #
# memory snapshots (owner decision 2: snapshot into the data dir each run)
# --------------------------------------------------------------------------- #


#: The memory snapshot never lives here. Audit M1-F4: raw MEMORY/USER text with 53
#: emails and 25 absolute paths was written into the evidence folder. Snapshots are
#: hashes plus gated text, in the plugin state dir, mode 600 - see
#: adapters/hermes/snapshot.py and adapters/hermes/evidence.py.


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def render_script_markdown(ir: EpisodeIR) -> str:
    lines = [
        f"# {ir.logline}",
        "",
        f"- episode: {ir.episode_id}",
        f"- format: {ir.format} ({len(ir.panels)} panels)",
        f"- arcs: {', '.join(ir.arc_ids)}",
        f"- dialogue: {ir.writer}",
        "",
    ]
    for number, panel in enumerate(ir.panels, start=1):
        lines.append(f"## Panel {number} - {panel.role} ({panel.shot})")
        if panel.caption:
            lines.append(f"*{panel.caption}*")
        lines.append(f"setting: {panel.setting} | cast: {', '.join(panel.cast)} | pose: {panel.pose} | expression: {panel.expression}")
        for line in panel.lines:
            lines.append(f"- {line.speaker}: \u201c{line.text}\u201d  [{', '.join(line.source_event_ids)}]")
        lines.append("")
    return "\n".join(lines)


def markdown_of(ir: EpisodeIR) -> str:
    """The rendered script, used for checks that must see exactly what is written."""
    return render_script_markdown(ir)


def evidence_by_event(
    gated: Iterable[GatedEvent], *, display: Mapping[str, str] | None = None
) -> dict[str, str]:
    """The gated text each event can ground a line with.

    Text plus its string fields: a line may only repeat what is in here, so a beat
    built from a tool name can only be talked about in those terms.
    """
    evidence: dict[str, str] = {}
    for event in gated:
        # The event's own identity is part of its evidence: a beat that names the
        # kind or the actor is repeating the record, not inventing.
        # R3-F4: no provenance in the evidence either - a model shown a record dump
        # writes one back. The structured sentence is the event's own fact.
        composed = compose_caption(event, display=display)
        parts: list[str] = [composed] if composed else []
        text = event.payload.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
        for key, value in sorted(event.payload.items()):
            if key in {"text", "gate"}:
                continue
            if isinstance(value, str) and value:
                parts.append(f"{key}: {value}")
            elif isinstance(value, list) and value and all(isinstance(item, str) for item in value):
                parts.append(f"{key}: {', '.join(value)}")
        evidence[event.id] = "\n".join(parts)
    return evidence


def _story_subset(beats: Sequence[Beat], limit: int) -> list[str]:
    """Event ids worth a span-level model pass: the beats the episode will use."""
    ranked = sorted(beats, key=lambda beat: (-beat.intensity, beat.ts, beat.id))[:limit]
    ids: list[str] = []
    for beat in ranked:
        ids.extend(beat.event_ids)
    return ids


def _text_for(source: HermesHistorySource, event: Event, limit: int) -> str | None:
    if event.content_ref is None:
        return None
    try:
        text = source.fetch_content(event.content_ref)
    except Exception:  # noqa: BLE001 - a missing text is not fatal, it is reported
        return None
    if not text:
        return None
    return text[:limit]


# --------------------------------------------------------------------------- #
# the pipeline
# --------------------------------------------------------------------------- #


def run_pipeline(
    config: PipelineConfig,
    *,
    source: HermesHistorySource | None = None,
) -> PipelineResult:
    result = PipelineResult()
    started = time.time()
    config.data_dir.mkdir(parents=True, exist_ok=True)

    own_source = source is None
    snapshot_store = SnapshotStore(config.state_dir)
    # Audit M1-F4 in one line: the private snapshot may not live inside the evidence
    # folder, whoever passes the paths.
    if os.environ.get("REEL_ALLOW_CUSTOM_STATE") != "1":
        state_root = snapshot_store.root.resolve()
        data_root = config.data_dir.resolve()
        for forbidden in (data_root, data_root.parent):
            try:
                state_root.relative_to(forbidden)
            except ValueError:
                continue
            raise ValueError(
                "state_dir must not sit inside the evidence folder "
                f"({state_root} is under {forbidden}): the memory snapshot is private "
                "(mode 600, hashes + gated text). Set REEL_ALLOW_CUSTOM_STATE=1 only "
                "for tests."
            )
    prior_hashes = snapshot_store.hashes_by_file()
    if source is None:
        source = HermesHistorySource(
            profiles=config.profiles,
            memory_snapshot=prior_hashes or None,
            snapshot_root=config.snapshot_root,
        )

    try:
        # A pinned window is what makes "the same input twice" meaningful on a live
        # system: without it, two runs minutes apart look at different weeks.
        now = config.until or datetime.now(tz=timezone.utc).timestamp()
        window = Window(since=config.since if config.since is not None else now - config.days * 86400, until=config.until)

        # ---- ingest ------------------------------------------------------
        events = list(source.events(window))
        result.events_ingested = len(events)
        result.timings["ingest_s"] = round(time.time() - started, 2)

        # Memory facts snapshot for the *next* run's diff (decision 2). Hashes and
        # gated text only, in the private state dir, never in evidence (M1-F4).
        try:
            current_facts = source.current_memory_facts()
        except Exception as exc:  # noqa: BLE001
            current_facts = {}
            result.problems.append(f"memory read failed: {type(exc).__name__}: {exc}")

        # ---- text --------------------------------------------------------
        candidates = [event for event in events if event.kind in TEXT_PRIORITY]
        candidates.sort(
            key=lambda item: (TEXT_PRIORITY[item.kind], item.ts, item.id)
        )
        texts: dict[str, str] = {}
        for event in candidates[: config.max_text_events]:
            text = _text_for(source, event, config.max_text_chars)
            if text:
                texts[event.id] = text
        result.events_with_text = len(texts)
        result.timings["text_s"] = round(time.time() - started, 2)

        # ---- gate: deterministic + vocabulary ----------------------------
        cache = ModelCache(config.data_dir / "cache")
        client: LLMClient
        if config.use_model:
            client = config.llm or OpenAICompatLLMClient.local()
        else:
            client = config.llm or NullLLM()
        cached = CachedLLM(client, cache, stage="m1")
        # R3-F6: the writer, title and entailment calls use the owner's main model via
        # the local API server. Redaction stays on the local model, so only post-gate
        # text ever reaches the other endpoint.
        writer_cached = (
            CachedLLM(config.writer_llm, cache, stage="m1")
            if config.writer_llm is not None
            else cached
        )

        rule_set = list(rules_from_snapshot())
        if getattr(config, "privacy", "private") == "public":
            rule_set.extend(public_rules())
        redactor = DeterministicRedactor(rule_set)
        # Agent/profile names are the cast, not internal projects: keep them out of the
        # learned-sensitive vocabulary or every character turns into "Agent N".
        cast_allowlist = tuple(sorted({*config.allowlist, *(p.name for p in source.info().profiles)}))
        model_gate = (
            ModelEntityGate(cached, allowlist=cast_allowlist) if config.use_model else None
        )
        gate = RedactionGate(
            redactor,
            privacy=getattr(config, "privacy", "private"),
            model_gate=model_gate,
            allowlist=cast_allowlist,
            max_chars=config.max_text_chars,
        )

        if model_gate is not None and texts:
            gate.learn_vocabulary(texts.values(), max_candidates=config.max_vocabulary)
        result.timings["vocabulary_s"] = round(time.time() - started, 2)

        gated: list[GatedEvent] = []
        gated_by_id: dict[str, GatedEvent] = {}
        for event in events:
            sealed = gate.gate_event(event, text=texts.get(event.id))
            if sealed is not None:
                gated.append(sealed)
                gated_by_id[sealed.id] = sealed
        result.gated = gate.report.gated
        result.quarantined = len(gate.report.quarantined)
        result.timings["gate_s"] = round(time.time() - started, 2)

        # ---- beats -------------------------------------------------------
        beats = beats_from_events(gated)
        result.beats = beats

        # ---- deep model pass on the story subset (decision 3, D5) --------
        if model_gate is not None:
            deep_ids = set(_story_subset(beats, config.max_deep_events))
            upgraded: list[GatedEvent] = []
            for event in events:
                existing = gated_by_id.get(event.id)
                if existing is None:
                    continue
                if event.id not in deep_ids:
                    upgraded.append(existing)
                    continue
                sealed = gate.gate_event(event, text=texts.get(event.id), deep=True)
                if sealed is None:
                    # Quarantined at the deeper level: drop it from the story.
                    continue
                upgraded.append(sealed)
            gated = [item for item in upgraded if item is not None]
            gated_by_id = {item.id: item for item in gated}
            result.gated = len(gated)
            result.quarantined = len(gate.report.quarantined)
            beats = beats_from_events(gated)
            result.beats = beats
            result.timings["deep_gate_s"] = round(time.time() - started, 2)

        result.gate_report = gate.report.as_dict()
        # Audit M1-F5: a run that quarantines more than 5% of what it gated is not
        # stable enough to build a story on.
        processed = result.gated + result.quarantined
        result.quarantine_rate = (result.quarantined / processed) if processed else 0.0
        if result.quarantine_rate > 0.05:
            result.problems.append(
                f"quarantine rate {result.quarantine_rate:.1%} exceeds 5%"
            )
        result.cache_stats = cache.stats()

        # ---- arcs, canon, episode ---------------------------------------
        # Audit M1-F2: an arc comes from ONE linked thread, never from stitched events.
        threads = build_threads(gated)
        arcs = build_arcs(
            threads,
            beats,
            events_by_id=gated_by_id,
            window_start=window.since,
        )
        result.threads = len(threads)
        result.arc_count = len(arcs)
        canon = build_canon(gated, beats, hero_names=(config.hero,), window_start=window.since)
        result.canon = canon

        if not arcs:
            result.problems.append("no arc could be built from this window")
            return result

        cast = [config.hero] + sorted(
            {
                beat.profile
                for beat in beats
                if beat.profile and beat.profile != config.hero
            }
        )
        writer: Any
        if config.writer is not None:
            writer = config.writer
        elif config.use_model:
            writer = LLMDialogueWriter(writer_cached, cast)
        else:
            # Round 8 / R7-F1: captions are written prose. With no model there is no
            # writer, so the run produces no strip and reports why.
            writer = TemplateDialogueWriter(cast, hero=config.hero)

        # Round 3 item 3: a script never shows a redaction marker. Every masked value
        # gets a stable fictional alias from the private alias book.
        alias_book = AliasBook.load(snapshot_store.root / "aliases.json")
        # Audit M1-F6: profiles are characters, not database ids.
        cast_map = build_cast_map(
            [beat.profile for beat in beats if beat.profile],
            hero=config.hero,
        )
        cast_map["default"] = cast_map.get("default", "Kensei")
        # R4-F1: the owner is a character in his own story, and no one is called "Assistant".
        cast_map["owner"] = config.hero
        cast_map = {
            profile: character
            for profile, character in cast_map.items()
            if character.strip().lower() not in {"assistant", "default", "agent", ""}
        }
        # A character name is released in the evidence, so it must survive the gate:
        # a profile whose name matches a learned sensitive term gets a neutral alias.
        safe_cast: dict[str, str] = {}
        for index, (profile, character) in enumerate(sorted(cast_map.items()), start=1):
            redacted, findings = gate.redact_text(character)
            safe_cast[profile] = character if not findings else f"Agent {index}"
        cast_map = safe_cast
        result.cast = summarise_cast(cast_map)

        # Audit M1-F1 + round 3: claims in both layers must be supported by the gated
        # content of the events the line cites.
        grounder = ClaimGate(
            writer_cached if config.use_model else None,
            allow=tuple(cast_map.values()) + tuple(config.allowlist) + (config.hero,),
        )
        # Who did what: only an actor of a cited event may speak its panel (R2-F2).
        actors_by_event: dict[str, str] = {}
        for event in gated:
            # Prefer the profile: on message events the actor is a tool name, and a tool
            # cannot speak. Fall back to the actor only when it is a known character.
            who = cast_map.get(event.profile) or cast_map.get(event.actor) or ""
            actors_by_event[event.id] = who

        evidence_map = evidence_by_event(gated, display=cast_map)
        structured_captions = {
            event.id: compose_caption(event, display=cast_map, hero=config.hero)
            for event in gated
        }

        # R3-F1: pick stories by meaning (sessions with a goal and an outcome, or task
        # families whose titles describe real work). Bookkeeping is never a story.
        selected, all_candidates = select_stories(gated, limit=max(4, config.episodes * 4))
        result.stories = [candidate.as_dict() for candidate in all_candidates[:12]]
        threads_index = {thread.key: thread for thread in threads}
        grouped_beats = beats_by_thread(beats, threads)
        thread_events: dict[str, list[GatedEvent]] = {}
        for event in gated:
            for thread in threads:
                if event.id in thread.event_ids:
                    thread_events.setdefault(thread.id, []).append(event)
                    break

        episodes: list[dict[str, Any]] = []
        ir: EpisodeIR | None = None
        skipped: list[dict[str, str]] = []
        used_anchors: set[str] = set()
        for candidate in selected:
            if len(episodes) >= max(1, config.episodes):
                break
            thread = threads_index.get(candidate.key)
            if thread is None:
                skipped.append({"key": candidate.key, "reason": "no thread for this story"})
                continue
            # R3-F2: the brief is the story spine, built from the thread's own text.
            brief = build_brief(
                thread.key,
                thread.kind,
                thread_events.get(thread.id, []),
                gate=grounder if config.use_model else None,
            )
            if not brief.ok:
                skipped.append(
                    {"key": candidate.key, "reason": f"brief not usable ({len(brief.turns)} turns)"}
                )
                continue
            thread_beats = grouped_beats.get(thread.id, [])
            thread_event_map = {event.id: event for event in thread_events.get(thread.id, [])}
            # R3-F3: panels are anchored on beats that carry gated text. A kanban thread
            # has lifecycle beats; a session thread usually has too few, so its beats
            # are built from the brief itself (round 4).
            if usable_anchor_count(thread_beats, brief=brief, evidence=evidence_map) >= 3:
                arc = build_arc(
                    thread_beats, thread=thread, events_by_id=thread_event_map
                )
                story_beats = thread_beats
            else:
                arc, story_beats = build_brief_arc(brief, thread_event_map)
            if arc is None:
                skipped.append({"key": candidate.key, "reason": "no arc"})
                continue
            # R4-F5: two episodes in one run must not stand on the same events.
            beat_index = {beat.id: beat for beat in (story_beats or thread_beats)}
            anchor_events = {
                event_id
                for beat_id in arc.roles.values()
                for event_id in (beat_index.get(beat_id).event_ids if beat_index.get(beat_id) else ())
            }
            if anchor_events & used_anchors:
                skipped.append(
                    {"key": candidate.key, "reason": "shares anchor events with an earlier episode"}
                )
                continue
            owner_texts = tuple(
                str((event.payload or {}).get("text", ""))
                for event in thread_events.get(thread.id, [])
                if str((event.payload or {}).get("role", "")) == "user"
                and str((event.payload or {}).get("text", "")).strip()
            )
            outcome_caption = ""
            if brief.outcome:
                for event in thread_events.get(thread.id, []):
                    if str((event.payload or {}).get("text", "")).strip() == brief.outcome.strip():
                        outcome_caption = compose_caption(event, display=cast_map, hero=config.hero)
                        break
                if not outcome_caption:
                    outcome_caption = trim_caption(brief.outcome)
            thread_facts = build_facts(
                brief, thread_event_map, display=cast_map, hero=config.hero
            )
            thread_facts_text = facts_text(thread_facts)
            thread_evidence_text = "\n".join(
                [brief.text()]
                + [evidence_map.get(event_id, "") for event_id in candidate.event_ids]
            )
            # R5-F4: if the model title fails grounding, fall back to the thread title
            # shortened on a word boundary - never to the owner's own message.
            raw_title = str(candidate.title or arc.title or "").strip()
            # R5-F4: the title is never the owner's own message. When the thread's only
            # title is that message, name the kind of work instead.
            owner_haystack = " ".join(owner_texts).lower()
            if raw_title and raw_title.lower()[:24] in owner_haystack:
                raw_title = "A session" if candidate.kind == "session" else "A task"
            derived_title = trim_caption(raw_title, max_words=6)
            title, title_source = write_title(
                writer_cached if config.use_model else None,
                beats=story_beats or thread_beats,
                derived=derived_title,
                hero=config.hero,
                gate=grounder,
                evidence=brief.text(),
                alias=alias_book.resolve,
            )
            index = len(episodes) + 1
            try:
                episode_ir = plan_episode(
                arc,
                story_beats or thread_beats,
                canon,
                format=config.format,
                season=config.season,
                number=config.number + index - 1,
                writer=writer,
                hero=config.hero,
                grounder=grounder,
                evidence=evidence_map,
                brief=brief,
                structured_captions=structured_captions,
                actors_by_event=actors_by_event,
                cast_map=cast_map,
                thread_evidence=thread_evidence_text,
                owner_texts=owner_texts,
                outcome_caption=outcome_caption,
                    facts=thread_facts,
                    facts_evidence=thread_facts_text,
                    title=title,
                )
            except EpisodeRefused as refused:
                skipped.append({"key": candidate.key, "reason": str(refused)})
                continue
            if len(episode_ir.panels) < 3:
                skipped.append({"key": candidate.key, "reason": "fewer than three panels"})
                continue
            episode_ir = apply_to_ir(episode_ir, alias_book)
            stray = masks_in(markdown_of(episode_ir))
            if stray:
                result.problems.append(
                    f"episode {index} still shows {len(stray)} redaction marker(s)"
                )
            episodes.append(
                {
                    "number": index,
                    "story_key": candidate.key,
                    "story_kind": candidate.kind,
                    "thread_kind": arc.thread_kind,
                    "thread_label": arc.thread_label,
                    "title": title,
                    "title_words": len(title.split()),
                    "header_title": episode_ir.logline,
                    "header_title_words": len(episode_ir.logline.split()),
                    "title_source": title_source,
                    "panels": len(episode_ir.panels),
                    "cliffhanger": episode_ir.cliffhanger,
                    "grounding": dict(episode_ir.grounding),
                    "brief": brief.as_dict(),
                    "facts": [fact.as_dict() for fact in thread_facts],
                    "ir": episode_ir,
                }
            )
            used_anchors |= anchor_events
            if index == 1:
                ir = episode_ir
                result.title = title
                result.title_source = title_source
        result.skipped_stories = skipped
        alias_book.save()
        if ir is None:
            # Honest empty run: no story could be told, but the run still reports its
            # gate, its stories and its skips so the reason is visible.
            result.problems.append("no episode could be planned")
            result.episodes = []
            result.skipped_stories = skipped
            result.timings["episode_s"] = round(time.time() - started, 2)
            result.timings["writer"] = "none"
        result.episodes = [
            {key: value for key, value in row.items() if key != "ir"} for row in episodes
        ]
        if ir is not None:
            result.grounding = dict(ir.grounding)
            result.cast = summarise_cast(cast_map)
            result.ir = ir
        result.timings["episode_s"] = round(time.time() - started, 2)
        result.llm_usage = {
            "redaction": getattr(client, "usage", lambda: {})(),
            "writer": getattr(config.writer_llm, "usage", lambda: {})(),
            "writer_endpoint": getattr(config.writer_llm, "name", "local"),
        }
        if isinstance(result.llm_usage["writer"], dict) and result.llm_usage["writer"].get("budget"):
            if result.llm_usage["writer"]["calls"] > result.llm_usage["writer"]["budget"]:
                result.problems.append("writer budget exceeded")

        # ---- gates on the output ----------------------------------------
        known = set(gated_by_id)
        if ir is None:
            # Nothing was written, so there is nothing to validate or scan. The run has
            # already reported why in problems.
            result.problems.extend([])
            markdown = ""
        else:
            result.problems.extend(validate_ir(ir, known_event_ids=known))
            markdown = render_script_markdown(ir)
        hits = leakscan.scan_text(markdown)
        if hits:
            result.problems.append(
                "leak scan found "
                + ", ".join(sorted({hit.pattern for hit in hits}))
                + " in the rendered script"
            )
        for panel in (ir.panels if ir is not None else ()):
            for line in panel.lines:
                name_hits = leakscan.scan_text(f"{line.speaker}: {line.text}")
                if any(hit.pattern == "high_entropy" for hit in name_hits):
                    result.problems.append(f"high-entropy token in {panel.id}")

        # ---- private memory snapshot (never evidence) --------------------
        memory_counts: dict[str, Any] = {"files": 0, "facts": 0}
        memory_hashes: dict[str, list[str]] = {}
        try:
            gated_by_file: dict[str, list[str]] = {}
            for key, facts in current_facts.items():
                values: list[str] = []
                for fact in facts:
                    try:
                        redacted, _ = gate.redact_text(fact)
                    except Exception:  # noqa: BLE001 - quarantine, do not store raw
                        redacted = "[REDACTED:health]"
                    values.append(redacted)
                gated_by_file[key] = values
            snapshot = build_snapshot(current_facts, captured_at=now, gated_text=gated_by_file)
            snapshot_store.save(snapshot)
            memory_counts = snapshot.counts()
            memory_hashes = snapshot.hashes_by_file()
        except Exception as exc:  # noqa: BLE001
            result.problems.append(f"memory snapshot failed: {type(exc).__name__}: {exc}")

        # ---- artifacts (every value re-checked by the evidence writer) ----
        try:
            write_json(
                config.data_dir / "beats.json",
                {"beats": [beat.as_dict() for beat in beats]},
                gate,
            )
            write_json(config.data_dir / "arcs.json", {"arcs": [arc.as_dict() for arc in arcs]}, gate)
            write_json(config.data_dir / "canon.json", canon.as_dict(), gate)
            if ir is not None:
                write_json(config.data_dir / "script-ir.json", ir.as_dict(), gate)
            for row in episodes:
                episode_ir = row["ir"]
                write_json(
                    config.data_dir / f"script-ir-{row['number']}.json",
                    episode_ir.as_dict(),
                    gate,
                )
                write_text(
                    config.data_dir / f"episode-{row['number']}-script.md",
                    render_script_markdown(episode_ir),
                    gate,
                )
            write_json(
                config.data_dir / "memory.json",
                {"counts": memory_counts, "hashes": memory_hashes},
                gate,
            )
            script_path = config.data_dir / "episode-script.md"
            write_text(script_path, markdown, gate)
            write_json(
                config.data_dir / "metrics.json",
                {
                    "generated_at": _now_iso(),
                    "window": {"since": window.since, "until": window.until, "days": config.days},
                    "events_ingested": result.events_ingested,
                    "events_with_text": result.events_with_text,
                    "gated": result.gated,
                    "quarantined": result.quarantined,
                    "beats": len(beats),
                    "arcs": len(arcs),
                    "panels": len(ir.panels) if ir is not None else 0,
                    "writer": ir.writer if ir is not None else "",
                    "grounding": result.grounding,
                    "episodes": result.episodes,
                    "llm_usage": result.llm_usage,
                    "stories": result.stories,
                    "skipped_stories": result.skipped_stories,
                    "threads": result.threads,
                    "title": result.title,
                    "header_title": ir.logline if ir is not None else "",
                    "header_title_words": len(ir.logline.split()) if ir is not None else 0,
                    "title_source": result.title_source,
                    "cast": result.cast,
                    "quarantine_rate": round(result.quarantine_rate, 4),
                    "primary_thread": (arcs[0].as_dict()["thread_kind"] if arcs else ""),
                    "causation_verified": (arcs[0].causation.get("verified") if arcs else None),
                    "gate": result.gate_report,
                    "cache": result.cache_stats,
                    "timings": result.timings,
                    "problems": result.problems,
                    "memory": memory_counts,
                },
                gate,
            )
        except EvidenceLeak as exc:
            result.problems.append(f"evidence refused: {exc}")

        result.artifacts = {
            name: name
            for name in (
                "canon.json",
                "beats.json",
                "arcs.json",
                "script-ir.json",
                "episode-script.md",
                "memory.json",
                "metrics.json",
            )
        }
        result.timings["total_s"] = round(time.time() - started, 2)
        return result
    finally:
        if own_source and source is not None:
            source.close()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _install_signal_cleanup() -> None:
    """Turn SIGTERM/SIGINT into a normal exit so snapshot copies are removed.

    ``weakref.finalize`` covers garbage collection and a normal interpreter exit,
    but a process killed by a signal never unwinds - which is how private copies of
    the user's databases end up lingering in the snapshot root.
    """

    def _handler(signum: int, _frame: object) -> None:
        raise SystemExit(128 + signum)

    for name in ("SIGTERM", "SIGINT"):
        signal_number = getattr(signal, name, None)
        if signal_number is None:
            continue
        try:
            signal.signal(signal_number, _handler)
        except (ValueError, OSError):  # not the main thread, or unsupported
            continue


def main(argv: Sequence[str] | None = None) -> int:
    _install_signal_cleanup()
    parser = argparse.ArgumentParser(
        prog="python -m adapters.hermes.pipeline",
        description="Scrollback Reel M1 pipeline: ingest, gate, beats, arcs, canon, episode.",
    )
    parser.add_argument("--data-dir", required=True, help="where artifacts and the cache live")
    parser.add_argument("--days", type=float, default=7.0)
    parser.add_argument(
        "--since",
        type=float,
        default=None,
        help="pin the window start (epoch seconds); also freezes determinism",
    )
    parser.add_argument(
        "--until", type=float, default=None, help="pin the window end (epoch seconds)"
    )
    parser.add_argument("--profile", action="append", default=None)
    parser.add_argument("--format", choices=("strip", "chapter"), default="strip")
    parser.add_argument("--number", type=int, default=1)
    parser.add_argument("--season", type=int, default=1)
    parser.add_argument(
        "--llm",
        choices=("none", "local"),
        default="none",
        help="none = deterministic only; local = the rig's serving route (no keys)",
    )
    parser.add_argument("--llm-url", default=os.environ.get("REEL_LLM_BASE_URL"))
    parser.add_argument("--llm-model", default=os.environ.get("REEL_LLM_MODEL", "auto"))
    parser.add_argument("--max-deep-events", type=int, default=MAX_DEEP_EVENTS)
    parser.add_argument(
        "--max-vocabulary",
        type=int,
        default=400,
        help="cap on distinct name candidates sent to the model (most frequent first)",
    )
    parser.add_argument(
        "--max-text-events",
        type=int,
        default=MAX_TEXT_EVENTS,
        help="cap on events whose text is fetched and gated (priority ordered)",
    )
    parser.add_argument(
        "--state-dir",
        default=None,
        help=(
            "private state dir for the memory snapshot (mode 600, outside evidence); "
            "defaults to $REEL_STATE_DIR or ~/.local/state/scrollback-reel"
        ),
    )
    parser.add_argument(
        "--episodes",
        type=int,
        default=1,
        help="how many threads to turn into scripts (each from a different thread)",
    )
    parser.add_argument(
        "--privacy",
        choices=("private", "public"),
        default="private",
        help="public masks money and health (D13); private is the owner's own view",
    )
    parser.add_argument("--json", action="store_true", help="print the metrics JSON")
    args = parser.parse_args(list(argv) if argv is not None else None)

    client: LLMClient | None = None
    if args.llm == "local":
        if not args.llm_url:
            parser.error("--llm local needs --llm-url or REEL_LLM_BASE_URL")
        # Reasoning models spend the whole budget on reasoning_content and return
        # content: null, which looks like an empty answer. Off for JSON tasks.
        client = OpenAICompatLLMClient(
            base_url=args.llm_url,
            model=args.llm_model,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )

    # The writer/title/entailment route is the plugin's ctx.llm (see
    # adapters/hermes/plugin_llm.py); this CLI only runs the pipeline itself, so it
    # either uses the local model for everything or nothing at all.
    writer_llm: Any = None
    writer_note = ""

    if client is not None:
        fallback_url = os.environ.get("REEL_LLM_FALLBACK_URL")
        fallback = (
            OpenAICompatLLMClient(
                base_url=fallback_url,
                model=os.environ.get("REEL_LLM_FALLBACK_MODEL", args.llm_model),
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )
            if fallback_url
            else None
        )
        client = FallbackLLM(client, fallback)

    config = PipelineConfig(
        data_dir=Path(args.data_dir).expanduser(),
        days=args.days,
        since=args.since,
        until=args.until,
        profiles=tuple(args.profile) if args.profile else None,
        format=args.format,
        season=args.season,
        number=args.number,
        use_model=args.llm != "none",
        max_deep_events=args.max_deep_events,
        max_text_events=args.max_text_events,
        max_vocabulary=args.max_vocabulary,
        privacy=args.privacy,
        episodes=max(1, args.episodes),
        writer_llm=writer_llm,
        state_dir=Path(args.state_dir).expanduser() if args.state_dir else None,
        llm=client,
    )
    result = run_pipeline(config)
    if writer_note == "api-server" and writer_llm is not None:
        result.problems = [p for p in result.problems]
    elif writer_note:
        result.timings["writer_note"] = writer_note
    payload = {
        "ok": result.ok,
        "events_ingested": result.events_ingested,
        "events_with_text": result.events_with_text,
        "gated": result.gated,
        "quarantined": result.quarantined,
        "beats": len(result.beats),
        "arcs": result.arc_count,
        "panels": len(result.ir.panels) if result.ir else 0,
        "writer": result.ir.writer if result.ir else "",
        "grounding": result.grounding,
        "threads": result.threads,
        "title": result.title,
        "title_source": result.title_source,
        "quarantine_rate": round(result.quarantine_rate, 4),
        "gate": result.gate_report,
        "cache": result.cache_stats,
        "timings": result.timings,
        "problems": result.problems,
        "artifacts": result.artifacts,
    }
    if args.json:
        print(json.dumps(payload, indent=1, sort_keys=True))
    else:
        print(f"events: {result.events_ingested} (with text: {result.events_with_text})")
        print(f"gated: {result.gated}, quarantined: {result.quarantined}")
        print(f"beats: {len(result.beats)}, arcs: {result.arc_count}")
        if result.ir:
            print(f"episode: {len(result.ir.panels)} panels, dialogue from {result.ir.writer}")
            print(f"script: {result.artifacts.get('script_md')}")
        if result.problems:
            print("problems:")
            for problem in result.problems[:10]:
                print(f"  - {problem}")
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
