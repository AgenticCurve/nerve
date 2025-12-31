"""Tests for Workflow class."""

from __future__ import annotations

import pytest

from nerve.core.nodes.base import FunctionNode
from nerve.core.session import Session
from nerve.core.workflow import Workflow, WorkflowContext


class TestWorkflowCreation:
    """Tests for Workflow creation and registration."""

    def test_creates_and_registers(self):
        """Workflow auto-registers with session on creation."""
        session = Session(name="test")

        async def my_fn(ctx: WorkflowContext) -> str:
            return "done"

        workflow = Workflow(id="test", session=session, fn=my_fn)

        assert "test" in session.workflows
        assert session.workflows["test"] is workflow

    def test_duplicate_id_raises(self):
        """Duplicate workflow ID raises ValueError."""
        session = Session(name="test")

        async def fn1(ctx: WorkflowContext) -> str:
            return "first"

        async def fn2(ctx: WorkflowContext) -> str:
            return "second"

        Workflow(id="test", session=session, fn=fn1)

        with pytest.raises(ValueError, match="conflicts with existing workflow"):
            Workflow(id="test", session=session, fn=fn2)

    def test_id_collision_with_node_raises(self):
        """Workflow ID cannot conflict with existing node."""
        session = Session(name="test")
        FunctionNode(id="runner", session=session, fn=lambda ctx: ctx.input)

        async def my_fn(ctx: WorkflowContext) -> str:
            return "done"

        with pytest.raises(ValueError, match="conflicts with existing node"):
            Workflow(id="runner", session=session, fn=my_fn)

    def test_id_collision_with_graph_raises(self):
        """Workflow ID cannot conflict with existing graph."""
        from nerve.core.nodes.graph import Graph

        session = Session(name="test")
        Graph(id="pipeline", session=session)

        async def my_fn(ctx: WorkflowContext) -> str:
            return "done"

        with pytest.raises(ValueError, match="conflicts with existing graph"):
            Workflow(id="pipeline", session=session, fn=my_fn)

    def test_description_from_docstring(self):
        """Description defaults to function docstring."""
        session = Session(name="test")

        async def documented_fn(ctx: WorkflowContext) -> str:
            """This is the documentation."""
            return "done"

        workflow = Workflow(id="test", session=session, fn=documented_fn)

        assert workflow.description == "This is the documentation."

    def test_description_override(self):
        """Explicit description overrides docstring."""
        session = Session(name="test")

        async def documented_fn(ctx: WorkflowContext) -> str:
            """This is the documentation."""
            return "done"

        workflow = Workflow(
            id="test",
            session=session,
            fn=documented_fn,
            description="Custom description",
        )

        assert workflow.description == "Custom description"

    def test_to_info(self):
        """to_info returns serializable WorkflowInfo."""
        session = Session(name="test")

        async def my_fn(ctx: WorkflowContext) -> str:
            return "done"

        workflow = Workflow(id="test", session=session, fn=my_fn, description="Test workflow")
        info = workflow.to_info()

        assert info.id == "test"
        assert info.description == "Test workflow"
        assert info.created_at is not None

        # to_dict should be JSON-serializable
        d = info.to_dict()
        assert d["id"] == "test"
        assert d["description"] == "Test workflow"
        assert "created_at" in d


class TestSessionWorkflowMethods:
    """Tests for Session workflow methods."""

    def test_get_workflow(self):
        """Session.get_workflow returns registered workflow."""
        session = Session(name="test")

        async def my_fn(ctx: WorkflowContext) -> str:
            return "done"

        workflow = Workflow(id="test", session=session, fn=my_fn)

        assert session.get_workflow("test") is workflow
        assert session.get_workflow("nonexistent") is None

    def test_list_workflows(self):
        """Session.list_workflows returns workflow IDs."""
        session = Session(name="test")

        async def fn1(ctx: WorkflowContext) -> str:
            return "1"

        async def fn2(ctx: WorkflowContext) -> str:
            return "2"

        Workflow(id="wf1", session=session, fn=fn1)
        Workflow(id="wf2", session=session, fn=fn2)

        workflows = session.list_workflows()
        assert "wf1" in workflows
        assert "wf2" in workflows
        assert len(workflows) == 2

    def test_delete_workflow(self):
        """Session.delete_workflow removes workflow."""
        session = Session(name="test")

        async def my_fn(ctx: WorkflowContext) -> str:
            return "done"

        Workflow(id="test", session=session, fn=my_fn)
        assert "test" in session.workflows

        result = session.delete_workflow("test")
        assert result is True
        assert "test" not in session.workflows

        # Deleting nonexistent returns False
        result = session.delete_workflow("test")
        assert result is False

    def test_to_dict_includes_workflows(self):
        """Session.to_dict includes workflow list."""
        session = Session(name="test")

        async def my_fn(ctx: WorkflowContext) -> str:
            return "done"

        Workflow(id="wf1", session=session, fn=my_fn)

        d = session.to_dict()
        assert "workflows" in d
        assert "wf1" in d["workflows"]
