"""Shared in-memory fake Supabase for unit tests.

One implementation of the query-builder subset our code uses, so filter/insert
semantics live in exactly one place. Tests import it as:

    from tests.fakes import FakeSupabase, patch_purge

The fake actually applies the filters the production queries build (eq/in/lt/
is-null with not_ negation, range pagination, limit, insert/update/delete), so
invariants are exercised for real rather than asserted against a call chain.
"""
from __future__ import annotations

from types import SimpleNamespace


class FakeQuery:
    def __init__(self, table_rows: list[dict]):
        self._rows = table_rows
        self._mode = "select"
        self._values: dict | list[dict] = {}
        self._filters: list = []  # (op, col, arg, negate)
        self._negate_next = False
        self._range: tuple[int, int] | None = None
        self._limit: int | None = None

    # builders -------------------------------------------------------
    def select(self, *_a, **_k):
        self._mode = "select"
        return self

    def insert(self, values, *_a, **_k):
        self._mode = "insert"
        self._values = values
        return self

    def update(self, values, *_a, **_k):
        self._mode = "update"
        self._values = values
        return self

    def delete(self, *_a, **_k):
        self._mode = "delete"
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val, False))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, list(vals), False))
        return self

    def lt(self, col, val):
        self._filters.append(("lt", col, val, False))
        return self

    def is_(self, col, _val):  # only ever called with "null"
        self._filters.append(("isnull", col, None, self._negate_next))
        self._negate_next = False
        return self

    @property
    def not_(self):
        self._negate_next = True
        return self

    def range(self, start, stop):
        self._range = (start, stop)
        return self

    def limit(self, n):
        self._limit = n
        return self

    # execution ------------------------------------------------------
    def _match(self, row) -> bool:
        for op, col, arg, negate in self._filters:
            if op == "eq":
                ok = row.get(col) == arg
            elif op == "in":
                ok = row.get(col) in arg
            elif op == "lt":
                v = row.get(col)
                ok = v is not None and v < arg
            elif op == "isnull":
                ok = row.get(col) is None
            else:  # pragma: no cover
                raise AssertionError(op)
            if negate:
                ok = not ok
            if not ok:
                return False
        return True

    def execute(self):
        if self._mode == "insert":
            new = self._values if isinstance(self._values, list) else [self._values]
            for r in new:
                self._rows.append(dict(r))
            return SimpleNamespace(data=[dict(r) for r in new])
        matched = [r for r in self._rows if self._match(r)]
        if self._mode == "update":
            for r in matched:
                r.update(self._values)
        elif self._mode == "delete":
            for r in matched:
                self._rows.remove(r)
        else:
            if self._range is not None:
                start, stop = self._range
                matched = matched[start : stop + 1]
            if self._limit is not None:
                matched = matched[: self._limit]
        return SimpleNamespace(data=[dict(r) for r in matched])


class FakeSupabase:
    def __init__(self, tables: dict[str, list[dict]]):
        self.tables = tables

    def table(self, name):
        return FakeQuery(self.tables.setdefault(name, []))


def patch_purge(monkeypatch, candidates):
    """Patch the purge seams in scripts.archive_and_purge; returns a calls dict."""
    import scripts.archive_and_purge as ap

    calls = {"removed": None, "tombstoned": None}
    monkeypatch.setattr(
        ap.queries, "list_archived_purgeable", lambda cutoff: list(candidates)
    )

    def fake_delete(paths):
        calls["removed"] = list(paths)
        return len(paths)

    def fake_tombstone(paths):
        calls["tombstoned"] = list(paths)
        return len(paths)

    monkeypatch.setattr(ap, "delete_from_storage", fake_delete)
    monkeypatch.setattr(ap.queries, "tombstone_archived", fake_tombstone)
    return calls
