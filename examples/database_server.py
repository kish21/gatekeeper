"""A demo twin of a database MCP server (the shape of the reference Postgres server).

``query`` is read-only (SELECT only, enforced here as well); ``execute`` runs a statement that
changes data. Backed by an in-memory SQLite database seeded with customers and orders.
"""

from __future__ import annotations

import logging
import sqlite3

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("database")
logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)

_DB = sqlite3.connect(":memory:")
_DB.executescript(
    """
    create table customers (id integer primary key, name text, email text, tier text);
    create table orders (id integer primary key, customer_id integer, total_cents integer,
                         status text);
    insert into customers values
      (4471, 'Amara Osei', 'amara@example.com', 'gold'),
      (4472, 'Ben Holt', 'ben@example.com', 'silver'),
      (4473, 'Chen Wei', 'chen@example.com', 'gold');
    insert into orders values
      (9001, 4471, 129900, 'shipped'),
      (9002, 4471, 4500, 'refund_requested'),
      (9003, 4473, 78000, 'processing');
    """
)


@mcp.tool()
def list_tables() -> str:
    """List tables and their columns."""
    out = []
    for (name,) in _DB.execute("select name from sqlite_master where type='table'"):
        cols = [c[1] for c in _DB.execute(f"pragma table_info({name})")]
        out.append(f"{name}({', '.join(cols)})")
    return "\n".join(out)


@mcp.tool()
def query(sql: str) -> str:
    """Run a read-only SELECT and return the rows."""
    if not sql.lstrip().lower().startswith("select"):
        raise ValueError("query() only runs SELECT statements; use execute() for changes")
    cur = _DB.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    lines = [" | ".join(cols)] + [" | ".join(str(v) for v in r) for r in rows]
    return "\n".join(lines) if rows else f"{' | '.join(cols)}\n(no rows)"


@mcp.tool()
def execute(sql: str) -> str:
    """Run a statement that CHANGES data (UPDATE, DELETE, INSERT). A MUTATION."""
    cur = _DB.execute(sql)
    _DB.commit()
    return f"ok, {cur.rowcount} row(s) affected"


if __name__ == "__main__":
    mcp.run()
