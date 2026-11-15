"""Local AI agent interface for FM Tactics Lab."""

__all__ = ["API", "PREFIX", "AgentError", "Client", "default_data_dir", "expand_seeds",
           "load_endpoint"]
__version__ = "1.0.0"

from .client import (API, PREFIX, AgentError, Client, default_data_dir, expand_seeds,
                     load_endpoint)
