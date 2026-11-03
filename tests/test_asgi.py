import runpy
from unittest import mock

import uvicorn


def test_access_log_is_off():
    with mock.patch.object(uvicorn, "run") as run:
        runpy.run_path("asgi.py", run_name="__main__")
    assert run.call_args.kwargs["access_log"] is False
