"""Runnable entry point for the ResearchOS API.

Usage::

    researchos-api                       # installed console script
    python -m researchos.api.main        # module form
    uvicorn researchos.api.main:app --reload

Environment variables
---------------------
RESEARCHOS_HOST : str, default ``127.0.0.1``
RESEARCHOS_PORT : int, default ``8000``
RESEARCHOS_RELOAD : bool, default ``false``
RESEARCHOS_MODEL_ENABLED : bool, default ``false`` (model gateway off)

See the README's "Model consumption" section for the ``RESEARCHOS_MODEL_*``
provider settings and the ``GET /api/model/usage`` endpoint.
"""

from __future__ import annotations

import os

from researchos.api.server import create_app

# ASGI application object used by ``uvicorn researchos.api.main:app``.
app = create_app()


def main() -> None:
    """Run the API with uvicorn."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - optional extra
        raise SystemExit(
            "uvicorn is required to run the API. "
            "Install it with `pip install ctxflow[researchos]`."
        ) from exc

    host = os.environ.get("RESEARCHOS_HOST", "127.0.0.1")
    port = int(os.environ.get("RESEARCHOS_PORT", "8000"))
    reload = os.environ.get("RESEARCHOS_RELOAD", "").lower() in {
        "1",
        "true",
        "yes",
    }

    uvicorn.run(
        "researchos.api.main:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
