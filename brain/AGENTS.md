Rules:
- always use uv run python to run python snippets and such
- always use uv add to add new packages
- always use modern typing hints, like dict[str, object] instead of Dict[str, Any]
- always document your functions in simple technical terms, using :param: and :return: where appropriate
- always fully type hint all params, args, returns, etc. -- partial type hints aren't sufficient (e.g. list[str] instead of just list)
- prefer collections.abc for generics, instead of typing.. e.g. collections.abc.AsyncIterator over typing.AsyncIterator
