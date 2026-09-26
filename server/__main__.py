"""Run the CreditCatch MCP server: python -m server"""

import sys

from . import config
from .app import mcp

problems = config.check()
if problems:
    for p in problems:
        print(f"config: {p}", file=sys.stderr)
    sys.exit(1)

print(f"CreditCatch MCP server on http://{config.HOST}:{config.PORT}/mcp "
      f"(mail: {config.MAIL_BACKEND}, demo mode: {config.DEMO_MODE})", file=sys.stderr)
mcp.run(transport="streamable-http")
