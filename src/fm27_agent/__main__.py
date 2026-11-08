"""Entry point for python -m fm27_agent."""
from __future__ import annotations

import sys


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "mcp":
        from .mcp import main as mcp_main
        return int(mcp_main(arguments[1:]))
    from .cli import main as cli_main
    return int(cli_main(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
