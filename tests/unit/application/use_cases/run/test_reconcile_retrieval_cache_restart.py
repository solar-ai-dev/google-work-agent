from google_work_agent.application.use_cases.run.reconcile_retrieval_cache_restart import (
    ReconcileRetrievalCacheRestartHandler,
)


def test_reconcile_retrieval_cache_restart__has_exact__application_owner() -> None:
    assert (
        ReconcileRetrievalCacheRestartHandler.__module__
        == "google_work_agent.application.use_cases.run.reconcile_retrieval_cache_restart"
    )
    assert ReconcileRetrievalCacheRestartHandler.__name__ == "ReconcileRetrievalCacheRestartHandler"
