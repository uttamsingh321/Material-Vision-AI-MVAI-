"""Material Vision AI - backend application package.

Layering (dependencies may only point downwards)::

    api / websocket      transport layer (FastAPI routers, WS endpoints)
    services             business use-cases, transaction boundaries
    tasks                background pipeline orchestration
    models / schemas     persistence entities and transport contracts
    database / config    infrastructure

See ``docs/ARCHITECTURE.md`` for the full component diagram and the
dependency-inversion rules enforced by the package layout.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
