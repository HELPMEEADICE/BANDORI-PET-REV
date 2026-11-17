"""Native extension loading and the retained DB-API diagnostic surface.

No SQL or Python sqlite3 connection is used here. Normal application queries use
one native domain call; this cursor exists for legacy callers of ``db._conn``.
"""


def native_class():
    try:
        from bandori_core._pet_db import NativeDatabase
    except ImportError as exc:
        raise RuntimeError(
            "Rust database extension is missing or incompatible. "
            "Run `python tools/build_db.py` with this Python interpreter before "
            "launching, or reinstall the matching application release."
        ) from exc
    return NativeDatabase


def open_native(path):
    return native_class()(str(path))


class NativeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.description = None
        self.rowcount = -1
        self.lastrowid = None
        self.arraysize = 1
        self._rows = iter(())

    def execute(self, sql, parameters=()):
        result = self.connection._native.raw_execute(sql, parameters)
        self.description = tuple((name, None, None, None, None, None, None)
                                 for name in result["columns"]) or None
        self.rowcount = result["rowcount"]
        self.lastrowid = result["lastrowid"]
        self._rows = iter(result["rows"])
        return self

    def executemany(self, sql, parameters):
        total = 0
        for row in parameters:
            self.execute(sql, row)
            total += max(0, self.rowcount)
        self.rowcount = total
        return self

    def fetchone(self):
        return next(self._rows, None)

    def fetchmany(self, size=None):
        from itertools import islice
        return list(islice(self._rows, self.arraysize if size is None else size))

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._rows)

    def close(self):
        self._rows = iter(())


class NativeConnection:
    def __init__(self, native):
        self._native = native

    def cursor(self):
        return NativeCursor(self)

    def execute(self, sql, parameters=()):
        return self.cursor().execute(sql, parameters)

    def executemany(self, sql, parameters):
        return self.cursor().executemany(sql, parameters)

    def commit(self):
        self._native.control("commit")

    def rollback(self):
        self._native.control("rollback")

    def interrupt(self):
        self._native.interrupt()

    @property
    def total_changes(self):
        return self._native.control("total_changes")

    @property
    def in_transaction(self):
        return self._native.control("in_transaction")

    def close(self):
        self._native.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
