"""Tests for DAG execution."""

import pytest

from nerve.core.dag import DAG, Task
from nerve.core.types import TaskStatus


class TestDAG:
    """Tests for DAG class."""

    @pytest.mark.asyncio
    async def test_simple_dag_execution(self):
        """Test simple DAG execution."""
        dag = DAG()

        async def task_a(ctx):
            return "result_a"

        async def task_b(ctx):
            return f"got_{ctx['a']}"

        dag.add_task(Task(id="a", execute=task_a))
        dag.add_task(Task(id="b", execute=task_b, depends_on=["a"]))

        results = await dag.run()

        assert results["a"].status == TaskStatus.COMPLETED
        assert results["a"].output == "result_a"
        assert results["b"].status == TaskStatus.COMPLETED
        assert results["b"].output == "got_result_a"

    def test_validate_catches_missing_dependency(self):
        """Test validate catches missing dependencies."""
        dag = DAG()

        async def noop(ctx):
            pass

        dag.add_task(Task(id="a", execute=noop, depends_on=["nonexistent"]))

        errors = dag.validate()
        assert len(errors) == 1
        assert "nonexistent" in errors[0]

    def test_chain_sets_dependencies(self):
        """Test chain method sets up dependencies."""
        dag = DAG()

        async def noop(ctx):
            pass

        dag.add_task(Task(id="a", execute=noop))
        dag.add_task(Task(id="b", execute=noop))
        dag.add_task(Task(id="c", execute=noop))

        dag.chain("a", "b", "c")

        assert "a" in dag.get_task("b").depends_on
        assert "b" in dag.get_task("c").depends_on

    def test_execution_order(self):
        """Test execution order respects dependencies."""
        dag = DAG()

        async def noop(ctx):
            pass

        dag.add_task(Task(id="c", execute=noop, depends_on=["b"]))
        dag.add_task(Task(id="b", execute=noop, depends_on=["a"]))
        dag.add_task(Task(id="a", execute=noop))

        order = dag.execution_order()
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")
