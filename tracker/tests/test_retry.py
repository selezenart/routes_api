import httpx
import pytest

from tracker.collector.client import TimetablesError
from tracker.collector.retry import call_with_retries


def flaky(*errors, result="ok"):
    calls = []

    def fn():
        calls.append(1)
        if len(calls) <= len(errors):
            raise errors[len(calls) - 1]
        return result

    fn.calls = calls
    return fn


def test_returns_result_without_sleeping():
    delays = []
    assert call_with_retries(flaky(), sleep=delays.append) == "ok"
    assert delays == []


def test_retries_with_exponential_backoff():
    delays = []
    fn = flaky(TimetablesError(503, "/x"), httpx.ConnectTimeout("t"), TimetablesError(429, "/x"))

    assert call_with_retries(fn, sleep=delays.append) == "ok"
    assert delays == [2.0, 4.0, 8.0]
    assert len(fn.calls) == 4


def test_delay_is_capped():
    delays = []
    fn = flaky(*[TimetablesError(500, "/x")] * 4)

    call_with_retries(fn, attempts=5, base_delay=10, max_delay=25, sleep=delays.append)

    assert delays == [10, 20, 25, 25]


def test_raises_last_error_after_all_attempts():
    delays = []
    fn = flaky(*[TimetablesError(500, "/a"), TimetablesError(502, "/b"), TimetablesError(504, "/c")])

    with pytest.raises(TimetablesError) as caught:
        call_with_retries(fn, attempts=3, sleep=delays.append)

    assert caught.value.status_code == 504
    assert len(fn.calls) == 3
    assert len(delays) == 2  # no sleep after the final attempt


@pytest.mark.parametrize("error", [TimetablesError(401, "/x"), TimetablesError(403, "/x"), ValueError("x")])
def test_other_errors_are_not_retried(error):
    delays = []
    fn = flaky(error)

    with pytest.raises(type(error)):
        call_with_retries(fn, sleep=delays.append)

    assert len(fn.calls) == 1
    assert delays == []
