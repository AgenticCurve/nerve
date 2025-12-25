"""Server factories - object creation patterns.

This package contains factory classes for creating various server objects:
- NodeFactory: Creates node instances based on backend type
"""

from nerve.server.factories.node_factory import NodeFactory

__all__ = [
    "NodeFactory",
]
