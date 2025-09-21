from __future__ import annotations

"""Neo4j client utilities: config loading and driver/session helpers.

Environment variables:
- NEO4J_URI (e.g., bolt://localhost:7687)
- NEO4J_USER
- NEO4J_PASSWORD
"""

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional

from neo4j import GraphDatabase, Driver, Session


@dataclass(frozen=True)
class Neo4jConfig:
    uri: str
    user: str
    password: str


def load_config(
    uri: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> Neo4jConfig:
    """Load Neo4j configuration from args or environment variables.

    Raises ValueError if required fields are missing.
    """
    resolved_uri = uri or os.getenv("NEO4J_URI", "").strip()
    resolved_user = user or os.getenv("NEO4J_USER", "").strip()
    resolved_password = password or os.getenv("NEO4J_PASSWORD", "").strip()

    missing = [
        name
        for name, val in [
            ("NEO4J_URI", resolved_uri),
            ("NEO4J_USER", resolved_user),
            ("NEO4J_PASSWORD", resolved_password),
        ]
        if not val
    ]
    if missing:
        raise ValueError(f"Missing Neo4j config for: {missing}")

    return Neo4jConfig(uri=resolved_uri, user=resolved_user, password=resolved_password)


def create_driver(config: Neo4jConfig) -> Driver:
    """Create a Neo4j driver instance."""
    return GraphDatabase.driver(config.uri, auth=(config.user, config.password))


@contextmanager
def neo4j_session(driver: Driver, database: Optional[str] = None) -> Iterator[Session]:
    """Context manager to open and close a Neo4j session."""
    session = driver.session(database=database) if database else driver.session()
    try:
        yield session
    finally:
        session.close()
