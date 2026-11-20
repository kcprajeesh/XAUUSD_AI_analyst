"""Private-pipe subprocess tests. Every child forbids actual network and SQLite access."""
from datetime import UTC, datetime, timedelta
from pathlib import Path
import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from app.data import refresh
from app.data.ingestion import MarketDataPipeline, RefreshRequest
from app.data.quota import RequestGate, RequestPolicy
from app.data.refresh import RefreshBudget, RefreshFailure, retrieve
from app.data.siftingio import SiftingIOClient
from app.data.storage import CandleStore

START = datetime(2026, 1, 1, tzinfo=UTC)
KEY = "synthetic-worker-credential"
BUDGET = RefreshBudget(5, 0.5, 2)


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    monkeypatch.setattr(refresh, "_parent_gate", None)
    monkeypatch.setattr(refresh, "_unresolved", [])


@pytest.fixture
def child(monkeypatch):
    processes = []
    def select(scenario):
        def launch():
            p = subprocess.Popen([sys.executable, "-B", str(Path(__file__).with_name("refresh_worker_fixture.py")), scenario],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                close_fds=True, start_new_session=True,
                env={"PATH": os.defpath, "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
            processes.append(p)
            return p
        monkeypatch.setattr(refresh, "_launch", launch)
        return processes
    yield select
    for p in processes:
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait(timeout=3)
        for pipe in (p.stdin, p.stdout):
            if pipe and not pipe.closed:
                pipe.close()


def request(**kwargs):
    return RefreshRequest(**dict(interval="1h", start=START, end=START + timedelta(hours=2000), **kwargs))


def run(spec=None, *, budget=BUDGET, policy=None, cancel=None):
    return retrieve(spec or request(), credential=KEY, timeout=(1, 1), policy=policy or RequestPolicy(),
                    history=(), budget=budget, cancel=cancel)


def test_valid_internal_continuation_and_confirmed_exit(child):
    processes = child("two_pages")
    result = run(policy=RequestPolicy(minimum_poll_interval_seconds=60, max_concurrent_requests=1))
    assert len(result.pages) == len(result.events) == 2
    assert processes[0].returncode == 0
    assert result.worker_pid == processes[0].pid
    assert all(pipe.closed for pipe in (processes[0].stdin, processes[0].stdout))


@pytest.mark.parametrize("scenario", ["slow", "dns", "late_exit", "ignore_term"])
def test_deadline_rejects_slow_dns_late_and_ignoring_workers(child, scenario):
    processes = child(scenario)
    began = time.monotonic()
    with pytest.raises(RefreshFailure, match="refresh_deadline_exceeded") as caught:
        run(budget=RefreshBudget(1.5, 0.5, 2))
    assert caught.value.cleanup_confirmed
    assert processes[0].returncode is not None
    assert caught.value.events  # Worker reached admission, rather than timing out only on import.
    assert time.monotonic() - began < 4
    if scenario == "ignore_term":
        assert processes[0].returncode == -signal.SIGKILL


def test_overall_deadline_across_pages(child):
    processes = child("multi_timeout")
    with pytest.raises(RefreshFailure, match="refresh_deadline_exceeded") as caught:
        run(budget=RefreshBudget(2.5, 0.5, 2))
    assert len(caught.value.events) == 2
    assert caught.value.cleanup_confirmed and processes[0].returncode is not None


@pytest.mark.parametrize("scenario,category", [
    ("malformed", "ipc_malformed"), ("duplicate_key", "ipc_malformed"),
    ("truncated", "ipc_truncated"), ("oversized", "ipc_oversized"),
    ("mismatch", "ipc_mismatched"), ("cursor_injection", "ipc_mismatched"),
    ("crash", "worker_abnormal_exit"),
    ("overlap", "pagination_overlap"), ("repeated", "pagination_cursor_repeated"),
])
def test_rejects_bad_or_incomplete_worker(child, scenario, category):
    processes = child(scenario)
    with pytest.raises(RefreshFailure, match=category) as caught:
        run()
    assert caught.value.cleanup_confirmed and processes[0].returncode is not None


def test_full_pipe_drained_and_total_bytes_bounded(child):
    child("full_pipe")
    assert len(run(request(limit=500)).pages[0].candles) == 500
    with pytest.raises(RefreshFailure, match="ipc_oversized"):
        run(request(limit=500), budget=RefreshBudget(5, 0.5, 2, max_result_bytes=1000))


def test_quota_shared_across_worker_processes(child):
    child("one_page")
    policy = RequestPolicy(max_requests_per_minute=1)
    assert len(run(policy=policy).events) == 1
    with pytest.raises(RefreshFailure, match="request_quota_exhausted"):
        run(policy=policy)
    assert not refresh._parent_gate._active


def test_concurrency_and_cancellation_across_workers(child):
    child("slow")
    policy = RequestPolicy(max_concurrent_requests=1)
    gate = RequestGate(policy)
    refresh._parent_gate = gate
    admitted = threading.Event()
    original = gate._begin
    def begin(*args, **kwargs):
        original(*args, **kwargs)
        admitted.set()
    gate._begin = begin
    cancel = threading.Event()
    failures = []
    def first():
        try:
            run(policy=policy, cancel=cancel)
        except RefreshFailure as e:
            failures.append(e)
    thread = threading.Thread(target=first)
    thread.start()
    try:
        assert admitted.wait(3)
        with pytest.raises(RefreshFailure, match="concurrency_limit"):
            run(policy=policy)
    finally:
        cancel.set()
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert failures[0].category == "refresh_cancelled" and failures[0].cleanup_confirmed
    assert not gate._active


def test_prelaunch_cancellation_creates_no_child(child):
    processes = child("one_page")
    event = threading.Event(); event.set()
    with pytest.raises(RefreshFailure, match="refresh_cancelled"):
        run(cancel=event)
    assert processes == []


def test_creation_time_consumes_budget(child, monkeypatch):
    processes = child("one_page")
    launch = refresh._launch
    def delayed():
        p = launch()
        time.sleep(0.15)
        return p
    monkeypatch.setattr(refresh, "_launch", delayed)
    with pytest.raises(RefreshFailure, match="refresh_deadline_exceeded"):
        run(budget=RefreshBudget(0.1, 0.5, 2))
    assert processes[0].returncode is not None


def test_parent_death_watchdog_exit_path(monkeypatch):
    from app.data import refresh_worker
    class Exit(BaseException): pass
    monkeypatch.setattr(refresh_worker.os, "getppid", lambda: 11)
    def exit(code):
        assert code == 71
        raise Exit()
    monkeypatch.setattr(refresh_worker.os, "_exit", exit)
    with pytest.raises(Exit):
        refresh_worker._watch_parent(10)


def test_cleanup_unresolved_blocks_success_and_further_workers(child, monkeypatch):
    processes = child("slow")
    monkeypatch.setattr(refresh, "_stop", lambda *_: False)
    with pytest.raises(RefreshFailure, match="cleanup_unresolved") as caught:
        run(budget=RefreshBudget(1.5, 0.1, 2))
    assert not caught.value.cleanup_confirmed
    assert refresh._unresolved[0][0] is processes[0]
    assert refresh._parent_gate._active
    with pytest.raises(RefreshFailure, match="cleanup_unresolved"):
        run()


def test_launch_arguments_and_environment_do_not_contain_credentials(monkeypatch):
    captured = {}
    class Stop(Exception): pass
    def popen(args, **kwargs):
        captured.update(args=args, **kwargs)
        raise Stop()
    monkeypatch.setattr(subprocess, "Popen", popen)
    with pytest.raises(Stop):
        refresh._launch()
    assert KEY not in repr(captured)
    assert "SIFTING_API_KEY" not in captured["env"]
    assert captured["close_fds"] and captured["start_new_session"]
    assert "shell" not in captured


def test_parent_only_persistence_and_failed_stage_preserves_current(child, tmp_path, monkeypatch):
    child("two_pages")  # Child explicitly forbids SQLite and socket connections.
    with CandleStore(tmp_path / "parent.synthetic.sqlite") as store:
        pipeline = MarketDataPipeline(SiftingIOClient(credential=KEY), store)
        assert len(pipeline.refresh(request(), budget=BUDGET, authorized=True)) == 2
        previous = store.sifting_candles("1h", closed_only=False)
        calls = []
        persist = store.persist_sifting_page
        def fail_second(*args, **kwargs):
            calls.append(os.getpid())
            if len(calls) == 2:
                raise RuntimeError("synthetic disk failure")
            return persist(*args, **kwargs)
        monkeypatch.setattr(store, "persist_sifting_page", fail_second)
        with pytest.raises(RuntimeError, match="synthetic disk failure"):
            pipeline.refresh(request(), budget=BUDGET, authorized=True)
        assert calls == [os.getpid(), os.getpid()]
        assert store.sifting_retrieval_status("1h") == "failed"
        assert store.sifting_candles("1h", closed_only=False) == previous


def test_failed_retrieval_never_persists_pages(child, tmp_path, monkeypatch):
    child("late_exit")
    with CandleStore(tmp_path / "late.synthetic.sqlite") as store:
        pipeline = MarketDataPipeline(SiftingIOClient(credential=KEY), store)
        def forbidden(*args, **kwargs):
            raise AssertionError("Late retrieval cannot persist pages")
        monkeypatch.setattr(store, "persist_sifting_page", forbidden)
        with pytest.raises(RefreshFailure, match="refresh_deadline_exceeded"):
            pipeline.refresh(request(), budget=RefreshBudget(1.5, 0.5, 2), authorized=True)
        assert store.sifting_retrieval_status("1h") == "failed"
        assert store.sifting_candles("1h") == ()


def test_refresh_requires_authorization_and_rejects_arbitrary_transport(tmp_path):
    with CandleStore(tmp_path / "auth.synthetic.sqlite") as store:
        pipeline = MarketDataPipeline(SiftingIOClient(credential=KEY, transport=lambda *_: None), store)
        with pytest.raises(RefreshFailure, match="refresh_not_authorized"):
            pipeline.refresh(request(), budget=BUDGET)
        with pytest.raises(RefreshFailure, match="worker_transport_not_supported"):
            pipeline.refresh(request(), budget=BUDGET, authorized=True)


def test_credential_transport_failure_is_redacted(child, capfd):
    child("credential_error")
    with pytest.raises(RefreshFailure, match="network_error") as caught:
        run()
    assert KEY not in str(caught.value) + repr(caught.value) + repr(caught.value.__dict__)
    captured = capfd.readouterr()
    assert KEY not in captured.out + captured.err


def test_deadline_monitor_stops_worker_during_slow_parent_admission(child):
    processes = child("slow")
    observed = []
    def blocked_parent_admission(*_):
        time.sleep(1.8)
        observed.append(processes[0].poll())
    with pytest.raises(RefreshFailure, match="refresh_deadline_exceeded"):
        retrieve(request(), credential=KEY, timeout=(1, 1), policy=RequestPolicy(), history=(),
                 budget=RefreshBudget(1, 0.3, 2), on_admission=blocked_parent_admission)
    assert observed[0] is not None


def test_parent_revalidates_page_even_if_worker_claims_it_is_valid(child, monkeypatch):
    child("one_page")
    def reject(*_):
        raise ValueError("Synthetic parent validation rejects page")
    monkeypatch.setattr(refresh.PageSequence, "add", reject)
    with pytest.raises(RefreshFailure, match="refresh_failed") as caught:
        run()
    assert caught.value.cleanup_confirmed


def test_history_merge_does_not_double_charge_completed_workers(child):
    child("one_page")
    policy = RequestPolicy(max_requests_per_minute=2)
    first = run(policy=policy)
    second = retrieve(request(), credential=KEY, timeout=(1, 1), policy=policy,
        history=tuple(at for _, at in first.events), budget=BUDGET)
    assert len(second.pages) == 1
    with pytest.raises(RefreshFailure, match="request_quota_exhausted"):
        run(policy=policy)


@pytest.mark.parametrize("field,value", [
    ("retrieval_seconds", 0), ("retrieval_seconds", float("inf")),
    ("cleanup_seconds", True), ("cleanup_seconds", 31),
    ("persistence_seconds", -1), ("max_result_bytes", 64_000_001),
])
def test_invalid_execution_budgets_rejected(field, value):
    values = dict(retrieval_seconds=5, cleanup_seconds=1, persistence_seconds=2)
    values[field] = value
    with pytest.raises(ValueError):
        RefreshBudget(**values)


def test_parent_validation_time_consumes_retrieval_budget(child, monkeypatch):
    processes = child("one_page")
    add = refresh.PageSequence.add
    def slow_validation(self, value):
        page = add(self, value)
        time.sleep(1.6)
        return page
    monkeypatch.setattr(refresh.PageSequence, "add", slow_validation)
    with pytest.raises(RefreshFailure, match="refresh_deadline_exceeded") as caught:
        run(budget=RefreshBudget(1, 0.5, 2))
    assert caught.value.cleanup_confirmed and processes[0].returncode is not None


def test_promotion_failure_rolls_back_current_generation(child, tmp_path):
    child("one_page")
    with CandleStore(tmp_path / "promote.synthetic.sqlite") as store:
        pipeline = MarketDataPipeline(SiftingIOClient(credential=KEY), store)
        pipeline.refresh(request(), budget=BUDGET, authorized=True)
        before = store.sifting_candles("1h", closed_only=False)
        # Fault injection in disposable storage, not a project schema change/migration.
        store.connection.execute("CREATE TEMP TRIGGER reject_promotion BEFORE UPDATE ON current_candles "
                                 "BEGIN SELECT RAISE(ABORT, 'synthetic promotion failure'); END")
        import sqlite3
        with pytest.raises(sqlite3.IntegrityError, match="synthetic promotion failure"):
            pipeline.refresh(request(), budget=BUDGET, authorized=True)
        assert store.sifting_candles("1h", closed_only=False) == before
        assert store.sifting_retrieval_status("1h") == "failed"


def test_production_entry_rejects_database_or_transport_selection_without_retrieval():
    from app.data.refresh_protocol import encode
    p = refresh._launch()
    try:
        bad = dict(v=1, type="start", attempt="synthetic", parent_pid=os.getpid(),
            spec=dict(interval="1h", start=START.isoformat(), end=(START + timedelta(hours=2)).isoformat(),
                      limit=2, max_pages=1), credential=KEY, timeout=[1, 1], database="forbidden")
        output, _ = p.communicate(encode(bad), timeout=5)
        assert p.returncode == 70 and output == b""
    finally:
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait(timeout=3)
        for pipe in (p.stdin, p.stdout):
            if pipe is not None:
                pipe.close()


def test_failure_bookkeeping_does_not_hide_cleanup_status(child, tmp_path, monkeypatch):
    child("slow")
    with CandleStore(tmp_path / "bookkeeping.synthetic.sqlite") as store:
        pipeline = MarketDataPipeline(SiftingIOClient(credential=KEY), store)
        def fail(*args):
            raise RuntimeError("synthetic bookkeeping failure")
        monkeypatch.setattr(store, "finish_sifting_request", fail)
        with pytest.raises(RefreshFailure, match="refresh_deadline_exceeded") as caught:
            pipeline.refresh(request(), budget=RefreshBudget(1, 0.5, 2), authorized=True)
        assert caught.value.cleanup_confirmed and caught.value.persistence_failure


@pytest.mark.parametrize("value", [True, 1.5, float("nan"), float("inf"), 0, -1])
def test_request_policy_rejects_unbounded_or_coerced_limits(value):
    with pytest.raises(ValueError):
        RequestPolicy(max_requests_per_minute=value)


@pytest.mark.parametrize("retained", [False, True])
def test_interrupted_launch_after_creation(child, monkeypatch, retained):
    processes = child("slow")
    launch = refresh._launch
    def interrupted():
        process = launch()
        if retained:
            refresh._launch_owner.state["process"] = process
        raise KeyboardInterrupt
    monkeypatch.setattr(refresh, "_launch", interrupted)
    with pytest.raises(RefreshFailure) as caught:
        run()
    if retained:
        assert caught.value.category == "refresh_cancelled"
        assert caught.value.cleanup_confirmed
        assert processes[0].returncode is not None
    else:
        assert caught.value.category == "cleanup_unresolved"
        assert not caught.value.cleanup_confirmed
        assert refresh._unresolved
        with pytest.raises(RefreshFailure, match="cleanup_unresolved"):
            run()
        assert len(processes) == 1


def test_unknown_launch_state_latches_but_prelaunch_cancel_does_not(monkeypatch):
    def interrupted():
        raise KeyboardInterrupt
    monkeypatch.setattr(refresh, "_launch", interrupted)
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(RefreshFailure, match="refresh_cancelled") as caught:
        run(cancel=cancelled)
    assert caught.value.cleanup_confirmed and not refresh._unresolved
    with pytest.raises(RefreshFailure, match="cleanup_unresolved") as caught:
        run()
    assert not caught.value.cleanup_confirmed and refresh._unresolved
    with pytest.raises(RefreshFailure, match="cleanup_unresolved"):
        run()


@pytest.mark.parametrize("scenario,category", [
    ("missing_terminal", "ipc_incomplete"), ("trailing", "ipc_mismatched"),
    ("invalid_cursor", "invalid_cursor"),
])
def test_terminal_and_cursor_diagnostics(child, scenario, category):
    processes = child(scenario)
    with pytest.raises(RefreshFailure) as caught:
        run()
    assert caught.value.category == category
    assert caught.value.cleanup_confirmed and processes[0].returncode is not None


@pytest.mark.parametrize("point", ["before", "during", "after", "interrupt_after"])
def test_promotion_cancellation_boundary(child, tmp_path, monkeypatch, point):
    child("one_page")
    with CandleStore(tmp_path / "cancel.synthetic.sqlite") as store:
        pipeline = MarketDataPipeline(SiftingIOClient(credential=KEY), store)
        pipeline.refresh(request(), budget=BUDGET, authorized=True)
        previous = store.sifting_candles("1h", closed_only=False)
        cancel = threading.Event()
        finish = store.finish_sifting_retrieval
        if point == "before":
            persist = store.persist_sifting_page
            def stage(*args, **kwargs):
                result = persist(*args, **kwargs)
                cancel.set()
                return result
            monkeypatch.setattr(store, "persist_sifting_page", stage)
        elif point == "during":
            # Cancellation occurs inside SQL promotion before its final guard/commit.
            store.connection.create_function("cancel_promotion", 0, lambda: cancel.set() or 0)
            store.connection.execute("CREATE TEMP TRIGGER cancel_promotion BEFORE UPDATE ON current_candles "
                                     "BEGIN SELECT cancel_promotion(); END")
        else:
            def finish_then_cancel(*args, **kwargs):
                result = finish(*args, **kwargs)
                if args[1] == "complete":
                    cancel.set()
                    if point == "interrupt_after":
                        raise KeyboardInterrupt
                return result
            monkeypatch.setattr(store, "finish_sifting_retrieval", finish_then_cancel)
        with pytest.raises(RefreshFailure) as caught:
            pipeline.refresh(request(), budget=BUDGET, authorized=True, cancel=cancel)
        if point in {"after", "interrupt_after"}:
            assert caught.value.category == "persistence_committed_reconciliation_required"
            assert caught.value.committed and caught.value.reconciliation_required
            assert store.sifting_retrieval_status("1h") == "complete"
            assert store.sifting_candles("1h", closed_only=False) != previous
        else:
            assert caught.value.category == "persistence_cancelled_or_expired"
            assert not caught.value.committed
            assert store.sifting_retrieval_status("1h") == "failed"
            assert store.sifting_candles("1h", closed_only=False) == previous


def test_production_launcher_retains_handle_before_return(child, monkeypatch):
    launch = refresh._launch
    child("slow")
    process = refresh._launch()
    monkeypatch.setattr(refresh.subprocess, "Popen", lambda *args, **kwargs: process)
    refresh._launch_owner.state = {}
    try:
        assert launch() is process
        assert refresh._launch_owner.state["process"] is process
    finally:
        refresh._launch_owner.state = None


def test_unknown_commit_status_requires_reconciliation(child, tmp_path, monkeypatch):
    child("one_page")
    with CandleStore(tmp_path / "unknown.synthetic.sqlite") as store:
        pipeline = MarketDataPipeline(SiftingIOClient(credential=KEY), store)
        finish = store.finish_sifting_retrieval
        statuses = []
        def interrupt_after_commit(*args, **kwargs):
            statuses.append(args[1])
            finish(*args, **kwargs)
            if args[1] == "complete":
                raise KeyboardInterrupt
        def unknown(*args, **kwargs):
            raise RuntimeError("Synthetic reconciliation failure")
        monkeypatch.setattr(store, "finish_sifting_retrieval", interrupt_after_commit)
        monkeypatch.setattr(store, "sifting_retrieval_status", unknown)
        with pytest.raises(RefreshFailure, match="persistence_reconciliation_required") as caught:
            pipeline.refresh(request(), budget=BUDGET, authorized=True)
        assert caught.value.reconciliation_required and caught.value.committed is None
        assert "failed" not in statuses
        assert store.sifting_candles("1h", closed_only=False)


def test_pending_attempt_cannot_launch_after_cleanup_latches(monkeypatch):
    pending = threading.Event()
    resume = threading.Event()
    gate = RequestGate(RequestPolicy())
    pagination = gate.pagination
    def reserve():
        lease = pagination()
        if threading.current_thread().name == "pending-refresh":
            pending.set()
            assert resume.wait(5)
        return lease
    monkeypatch.setattr(gate, "pagination", reserve)
    monkeypatch.setattr(refresh, "_parent_gate", gate)
    launches = []
    def unknown_launch():
        launches.append(threading.current_thread().name)
        raise KeyboardInterrupt
    monkeypatch.setattr(refresh, "_launch", unknown_launch)
    failures = []
    def pending_attempt():
        try:
            run()
        except RefreshFailure as error:
            failures.append(error)
    thread = threading.Thread(target=pending_attempt, name="pending-refresh")
    thread.start()
    try:
        assert pending.wait(5)
        with pytest.raises(RefreshFailure, match="cleanup_unresolved"):
            run()
        assert refresh._unresolved
    finally:
        resume.set()
        thread.join(5)
    assert not thread.is_alive()
    assert len(launches) == 1
    assert failures[0].category == "cleanup_unresolved"
    assert not gate._active


@pytest.mark.parametrize("outcome", ["cancel", "unknown", "success"])
@pytest.mark.parametrize("setting", ["busy_timeout", "progress_handler"])
def test_restoration_failure_preserves_committed_reconciliation(child, tmp_path, monkeypatch, outcome, setting):
    unknown = outcome == "unknown"
    child("one_page")
    with CandleStore(tmp_path / "restoration.synthetic.sqlite") as store:
        pipeline = MarketDataPipeline(SiftingIOClient(credential=KEY), store)
        connection = store.connection
        committed = threading.Event()
        cancel = threading.Event()
        class RestorationFailure(RuntimeError): pass
        class ConnectionProxy:
            def __getattr__(self, name):
                return getattr(connection, name)
            def execute(self, sql, *args):
                if committed.is_set() and setting == "busy_timeout" and sql.startswith("PRAGMA busy_timeout="):
                    raise RestorationFailure("synthetic settings restoration failure")
                return connection.execute(sql, *args)
            def set_progress_handler(self, handler, steps):
                if committed.is_set() and setting == "progress_handler" and handler is None:
                    raise RestorationFailure("synthetic settings restoration failure")
                return connection.set_progress_handler(handler, steps)
            def __enter__(self):
                connection.__enter__()
                return self
            def __exit__(self, *args):
                return connection.__exit__(*args)
        monkeypatch.setattr(store, "connection", ConnectionProxy())
        finish = store.finish_sifting_retrieval
        statuses = []
        def finish_then_cancel(*args, **kwargs):
            statuses.append(args[1])
            result = finish(*args, **kwargs)
            if args[1] == "complete":
                committed.set()
                if outcome != "success":
                    cancel.set()
                if unknown:
                    raise KeyboardInterrupt
            return result
        monkeypatch.setattr(store, "finish_sifting_retrieval", finish_then_cancel)
        if unknown:
            def unavailable(*args, **kwargs):
                raise RuntimeError("synthetic unreadable commit status")
            monkeypatch.setattr(store, "sifting_retrieval_status", unavailable)
        try:
            with pytest.raises(RefreshFailure) as caught:
                pipeline.refresh(request(), budget=BUDGET, authorized=True, cancel=cancel)
            failure = caught.value
            assert failure.category == ("persistence_reconciliation_required" if unknown else
                                        "persistence_committed_reconciliation_required")
            assert failure.committed is (None if unknown else True)
            assert failure.reconciliation_required
            assert (setting, "RestorationFailure") in failure.cleanup_failures
            assert statuses == ["complete"]
            assert store.sifting_candles("1h")
        finally:
            connection.set_progress_handler(None, 0)
            monkeypatch.setattr(store, "connection", connection)
