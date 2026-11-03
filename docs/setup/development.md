# Development setup

Run the service locally and run its tests.

## Run the service

You need Python 3.11 or newer.

```sh
pip install -r requirements.txt
python asgi.py
```

The service listens on `http://localhost:8010`. The API reference is at `/docs`.

Or run it with Docker:

```sh
docker build -t schulymicrosoft .
docker run -p 8010:8010 schulymicrosoft
```

## Run the tests

The tests are fully mocked and make no calls to Microsoft.

```sh
python -m pytest tests -q
```

## Rules for changes

- Don't add credential endpoints other than the existing password sign-in.
- Keep passwords out of logs, sign-in jobs, errors, and responses.
- Keep the service to one process. Don't add workers or replicas.
- Use only the public OutNote and Entrance APIs.
- Keep dependencies pointing inward: `domain`, then `application`, then `infrastructure` and `api`. `tests/test_architecture.py` fails otherwise.

For the workflow, see [Contribute](/contribute/).
