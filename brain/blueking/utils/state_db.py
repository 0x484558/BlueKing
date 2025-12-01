import os
import pickle
from typing import ContextManager, final, override, cast, Self
from typing_extensions import Buffer
from collections.abc import MutableMapping, Iterator, Iterable

import lmdb
from pydantic import BaseModel


class BrainState(BaseModel):
    username: str = ""
    message: str = ""
    reply: str = ""


@final
class LmdbDict(MutableMapping[str, object]):
    """
    LMDB-backed mutable mapping that exposes attributes for state access.
    """

    _env: lmdb.Environment | None = None
    _db: lmdb._Database | None = None

    def __new__(
        cls: type[Self], path: str | None = None, map_size: int = 1 << 30
    ) -> Self:
        """
        Allocate the mapping instance while preserving pydantic compatibility.

        :param path: Optional filesystem path for the LMDB environment.
        :param map_size: Maximum size in bytes of the database map.
        :return: New mapping instance.
        """
        return cast(Self, super().__new__(cls))

    def __init__(self, path: str | None = None, map_size: int = 1 << 30):
        """
        Initialize the LMDB environment and database handle.

        :param path: Filesystem path for the LMDB environment.
        :param map_size: Maximum size in bytes of the database map.
        :return: None.
        """
        if path is None:
            path = os.environ.get("BLUEKING_STATE_DB_PATH", "./state.db")

        object.__setattr__(self, "_env", lmdb.open(
            path,
            map_size=map_size,
            max_dbs=1,
            writemap=False,
            sync=True,
            metasync=True,
            lock=True,
            readahead=True
        ))
        object.__setattr__(self, "_db", cast(lmdb.Environment, self._env).open_db())

    @override
    def __getitem__(self, key: str) -> object:
        """
        Fetch a value from the database for the provided key.

        :param key: Key to retrieve.
        :return: Deserialized value.
        :raises KeyError: When the key does not exist.
        """
        k = str(key).encode()
        with cast(lmdb.Environment, self._env).begin() as txn:
            val = cast(Buffer | None, txn.get(k))
            if val is None:
                raise KeyError(key)
            return pickle.loads(val)

    @override
    def __setitem__(self, key: str, value: object) -> None:
        """
        Store a value in the database under the provided key.

        :param key: Key to set.
        :param value: Serializable value to persist.
        :raises RuntimeError: When the write fails.
        :return: None.
        """
        k = str(key).encode()
        v = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        with cast(lmdb.Environment, self._env).begin(write=True) as txn:
            if not txn.put(k, v):
                raise RuntimeError("put failed")

    @override
    def __delitem__(self, key: str) -> None:
        """
        Remove a key from the database.

        :param key: Key to delete.
        :raises KeyError: When the key does not exist.
        :return: None.
        """
        k = str(key).encode()
        with cast(lmdb.Environment, self._env).begin(write=True) as txn:
            if not txn.delete(k):
                raise KeyError(key)

    @override
    def __iter__(self) -> Iterator[str]:
        """
        Iterate over stored keys in the database.

        :return: Iterator of decoded keys.
        """
        with cast(lmdb.Environment, self._env).begin() as txn:
            with cast(ContextManager[Iterable[tuple[bytes, object]]], txn.cursor()) as cur:
                for k, _ in cur:
                    yield k.decode()

    @override
    def __len__(self) -> int:
        """
        Return the number of entries in the database.

        :return: Entry count.
        """
        with cast(lmdb.Environment, self._env).begin() as txn:
            return cast(int, txn.stat(self.db)["entries"])

    @override
    def __setattr__(self, name: str, value: object) -> None:
        """
        Assign attribute-like values into the underlying mapping.

        :param name: Attribute name to set.
        :param value: Value to store.
        :return: None.
        """
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        self[name] = value

    @override
    def __delattr__(self, name: str) -> None:
        """
        Delete an attribute-like key from the mapping.

        :param name: Attribute name to delete.
        :raises AttributeError: When the key does not exist.
        :return: None.
        """
        if name.startswith("_"):
            super().__delattr__(name)
        else:
            try:
                del self[name]
            except KeyError as exc:
                raise AttributeError(name) from exc

    def __getattr__(self, name: str) -> object:
        """
        Fetch stored values as attributes.

        :param name: Attribute name to look up.
        :return: Stored value.
        :raises AttributeError: When the key is missing.
        """
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __type__(self) -> type:
        """
        Provide the BrainState type for compatibility with Flow generics.

        :return: BrainState type.
        """
        return type(BrainState)
