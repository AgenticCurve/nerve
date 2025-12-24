"""Tests for nerve.core.nodes.cancellation module."""

import asyncio

import pytest

from nerve.core.nodes.cancellation import CancellationToken, CancelledException


class TestCancelledException:
    """Tests for CancelledException."""

    def test_is_exception(self):
        """Test it's a proper exception."""
        with pytest.raises(CancelledException):
            raise CancelledException()

    def test_message(self):
        """Test exception message."""
        error = CancelledException()
        assert "cancelled" in str(type(error).__name__).lower()


class TestCancellationToken:
    """Tests for CancellationToken."""

    def test_initial_state(self):
        """Test initial state is not cancelled."""
        token = CancellationToken()
        assert token.is_cancelled is False

    def test_cancel(self):
        """Test cancel sets the flag."""
        token = CancellationToken()
        token.cancel()
        assert token.is_cancelled is True

    def test_cancel_idempotent(self):
        """Test cancel is idempotent."""
        token = CancellationToken()
        token.cancel()
        token.cancel()  # Should not raise
        assert token.is_cancelled is True

    def test_check_not_cancelled(self):
        """Test check does not raise when not cancelled."""
        token = CancellationToken()
        # Should not raise
        token.check()

    def test_check_cancelled(self):
        """Test check raises when cancelled."""
        token = CancellationToken()
        token.cancel()

        with pytest.raises(CancelledException):
            token.check()

    @pytest.mark.asyncio
    async def test_wait_completes_on_cancel(self):
        """Test wait completes when cancel is called."""
        token = CancellationToken()

        async def cancel_after_delay():
            await asyncio.sleep(0.1)
            token.cancel()

        async def wait_for_cancel():
            await token.wait()

        # Start both tasks
        wait_task = asyncio.create_task(wait_for_cancel())
        cancel_task = asyncio.create_task(cancel_after_delay())

        # Both should complete
        await asyncio.gather(wait_task, cancel_task)
        assert token.is_cancelled is True

    def test_reset(self):
        """Test reset clears the cancelled state."""
        token = CancellationToken()
        token.cancel()
        assert token.is_cancelled is True

        token.reset()
        assert token.is_cancelled is False

    def test_reset_allows_recheck(self):
        """Test reset allows check to pass again."""
        token = CancellationToken()
        token.cancel()

        with pytest.raises(CancelledException):
            token.check()

        token.reset()

        # Should not raise now
        token.check()

    @pytest.mark.asyncio
    async def test_cooperative_cancellation_pattern(self):
        """Test typical cooperative cancellation pattern."""
        token = CancellationToken()
        work_done = []

        async def worker():
            for i in range(10):
                token.check()  # Check before each unit of work
                work_done.append(i)
                await asyncio.sleep(0.05)

        async def canceller():
            await asyncio.sleep(0.15)  # Cancel after ~3 iterations
            token.cancel()

        # Start worker and canceller
        worker_task = asyncio.create_task(worker())
        cancel_task = asyncio.create_task(canceller())

        with pytest.raises(CancelledException):
            await asyncio.gather(worker_task, cancel_task)

        # Should have done some work but not all
        assert len(work_done) > 0
        assert len(work_done) < 10
