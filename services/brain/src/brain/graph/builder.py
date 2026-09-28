"""Durable, bounded LangGraph assembly for the maintenance workflow."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
import dataclasses
import json
from enum import Enum
from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import RunnableConfig
from pydantic import BaseModel

from brain.graph.nodes import (
    GraphDependencies,
    approval_node,
    audit_node,
    context_node,
    diagnosis_node,
    dispatch_node,
    escalate_node,
    gate_node,
    intake_node,
    p0_node,
    route_after_diagnosis,
    route_after_dispatch,
    route_after_gate,
    route_after_intake,
    route_after_safety,
    safety_node,
)
from brain.graph.state import TicketState


MAX_GRAPH_STEPS = 12


class TicketStateCheckpointSerializer(JsonPlusSerializer):
    """Preserve immutable tuples and revalidate Pydantic handoffs on resume.

    LangGraph's default MessagePack serializer restores Pydantic models with
    ``model_construct`` and turns tuples into lists. That bypasses this project's
    strict handoff contracts. The checkpoint payload contains no raw resident
    content, so JSON is an appropriate auditable format here.
    """

    def dumps(self, obj: Any) -> bytes:
        return json.dumps(
            _checkpoint_value(obj),
            default=self._default,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

    def dumps_typed(self, obj: Any) -> tuple[str, bytes]:
        return "json", self.dumps(obj)


class MaintenanceGraph:
    """The public graph surface that enforces the non-negotiable step limit."""

    def __init__(self, compiled: Any) -> None:
        self._compiled = compiled

    async def ainvoke(
        self, input: TicketState | None, config: RunnableConfig, **kwargs: Any
    ) -> TicketState:
        result = await self._compiled.ainvoke(
            _state_values(input), _capped_config(config), **kwargs
        )
        return TicketState.model_validate(result)

    def invoke(
        self, input: TicketState | None, config: RunnableConfig, **kwargs: Any
    ) -> TicketState:
        result = self._compiled.invoke(
            _state_values(input), _capped_config(config), **kwargs
        )
        return TicketState.model_validate(result)

    async def astream(
        self, input: TicketState | None, config: RunnableConfig, **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        async for update in self._compiled.astream(
            _state_values(input), _capped_config(config), **kwargs
        ):
            yield cast(dict[str, Any], update)

    async def aget_state(self, config: RunnableConfig) -> Any:
        return await self._compiled.aget_state(_checkpoint_config(config))

    def get_state(self, config: RunnableConfig) -> Any:
        return self._compiled.get_state(_checkpoint_config(config))

    def get_graph(self, **kwargs: Any) -> Any:
        return self._compiled.get_graph(**kwargs)


def build_maintenance_graph(
    dependencies: GraphDependencies, *, checkpointer: BaseCheckpointSaver
) -> MaintenanceGraph:
    """Compile the P0-first workflow with durable checkpoints and approval pause."""

    # LangGraph owns a structural mapping only. Each bound node immediately
    # restores the strict, frozen TicketState contract before doing any work.
    # This also avoids coupling the durable runtime to LangGraph's deprecated
    # Pydantic-model schema introspection.
    workflow = StateGraph(dict)
    workflow.add_node("screen_safety", _bind(safety_node, dependencies))
    workflow.add_node("page_p0", _bind(p0_node, dependencies))
    workflow.add_node("normalize_intake", _bind(intake_node, dependencies))
    workflow.add_node("assemble_context", _bind(context_node, dependencies))
    workflow.add_node("run_diagnosis", _bind(diagnosis_node, dependencies))
    workflow.add_node("plan_dispatch", _bind(dispatch_node, dependencies))
    workflow.add_node("audit_policy", _bind(audit_node, dependencies))
    workflow.add_node("apply_gate", _bind(gate_node, dependencies))
    workflow.add_node("approval", _bind_terminal(approval_node))
    workflow.add_node("route_escalation", _bind_terminal(escalate_node))

    workflow.add_edge(START, "screen_safety")
    workflow.add_conditional_edges(
        "screen_safety",
        _bind_route(route_after_safety),
        {
            "p0": "page_p0",
            "context": "normalize_intake",
            "escalate": "route_escalation",
        },
    )
    workflow.add_conditional_edges(
        "normalize_intake",
        _bind_route(route_after_intake),
        {"context": "assemble_context", "escalate": "route_escalation"},
    )
    workflow.add_edge("assemble_context", "run_diagnosis")
    workflow.add_conditional_edges(
        "run_diagnosis",
        _bind_route(route_after_diagnosis),
        {"dispatch": "plan_dispatch", "gate": "apply_gate"},
    )
    workflow.add_conditional_edges(
        "plan_dispatch",
        _bind_route(route_after_dispatch),
        {"audit": "audit_policy", "gate": "apply_gate"},
    )
    workflow.add_edge("audit_policy", "apply_gate")
    workflow.add_conditional_edges(
        "apply_gate",
        _bind_route(route_after_gate),
        {
            "approve": "approval",
            "escalate": "route_escalation",
        },
    )
    workflow.add_edge("page_p0", END)
    workflow.add_edge("approval", END)
    workflow.add_edge("route_escalation", END)

    compiled = workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["approval"],
    )
    return MaintenanceGraph(compiled)


@contextmanager
def open_postgres_checkpointer(
    connection_string: str, *, initialize: bool = False
) -> Iterator[PostgresSaver]:
    """Open a synchronous ``PostgresSaver`` for a synchronous composition root.

    ``initialize`` is for the migration/bootstrap job only. Normal application
    startups use the already-created checkpoint tables and avoid concurrent DDL.
    """

    with PostgresSaver.from_conn_string(connection_string) as checkpointer:
        checkpointer.serde = TicketStateCheckpointSerializer()
        if initialize:
            checkpointer.setup()
        yield checkpointer


@asynccontextmanager
async def open_async_postgres_checkpointer(
    connection_string: str, *, initialize: bool = False
) -> AsyncIterator[AsyncPostgresSaver]:
    """Open the async ``PostgresSaver`` counterpart used by this async workflow."""

    async with AsyncPostgresSaver.from_conn_string(
        connection_string, serde=TicketStateCheckpointSerializer()
    ) as checkpointer:
        if initialize:
            await checkpointer.setup()
        yield checkpointer


def _bind(function: Any, dependencies: GraphDependencies) -> Any:
    async def bound(state: dict[str, Any], config: RunnableConfig) -> Any:
        return await function(
            TicketState.model_validate(state), config, dependencies=dependencies
        )

    return bound


def _bind_terminal(function: Any) -> Any:
    def bound(state: dict[str, Any]) -> Any:
        return function(TicketState.model_validate(state))

    return bound


def _bind_route(function: Any) -> Any:
    def bound(state: dict[str, Any]) -> Any:
        return function(TicketState.model_validate(state))

    return bound


def _capped_config(config: RunnableConfig) -> dict[str, Any]:
    checkpoint_config = _checkpoint_config(config)
    requested = config.get("recursion_limit")
    if requested is not None and requested != MAX_GRAPH_STEPS:
        raise ValueError(
            f"maintenance graph requires recursion_limit={MAX_GRAPH_STEPS}"
        )
    checkpoint_config["recursion_limit"] = MAX_GRAPH_STEPS
    return checkpoint_config


def _checkpoint_config(config: RunnableConfig) -> dict[str, Any]:
    configurable = config.get("configurable", {})
    thread_id = (
        configurable.get("thread_id") if isinstance(configurable, dict) else None
    )
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise ValueError("maintenance graph requires configurable.thread_id")
    return dict(config)


def _state_values(state: TicketState | None) -> dict[str, object] | None:
    if state is None:
        return None
    return {
        field_name: getattr(state, field_name)
        for field_name in TicketState.model_fields
    }


def _checkpoint_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return _constructor_value(value.__class__, args=(value.value,))
    if isinstance(value, BaseModel):
        return _constructor_value(
            value.__class__,
            kwargs=_checkpoint_value(value.model_dump(mode="python")),
        )
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _constructor_value(
            value.__class__,
            kwargs={
                field.name: _checkpoint_value(getattr(value, field.name))
                for field in dataclasses.fields(value)
            },
        )
    if isinstance(value, tuple):
        return _constructor_value(
            tuple, args=([_checkpoint_value(item) for item in value],)
        )
    if isinstance(value, list):
        return [_checkpoint_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _checkpoint_value(item) for key, item in value.items()}
    return value


def _constructor_value(
    constructor: type[Any],
    *,
    args: tuple[object, ...] | None = None,
    kwargs: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "lc": 2,
        "type": "constructor",
        "id": (*constructor.__module__.split("."), constructor.__name__),
    }
    if args is not None:
        payload["args"] = args
    if kwargs is not None:
        payload["kwargs"] = kwargs
    return payload
