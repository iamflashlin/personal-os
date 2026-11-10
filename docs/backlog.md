# Backlog

Known gaps that are accepted for now. Each item names where it came from and the
smallest change that would close it. Promote an item to a task card in `docs/tasks/`
before working on it.

| # | Gap | Source | Possible fix |
|---|---|---|---|
| 1 | Audit redaction is pattern based. Secrets written as prose ("my password is hunter2") or as unquoted multi-word values (`secret: abc def` keeps `def`) are not caught. | T-0002, ADR 0009 §5 | Redact whole free-text fields (e.g. `notes`) in the audit copy and log only their length and hash, or add a dedicated secret scanner. |
| 2 | Task `depends_on` only rejects self-dependency. Longer cycles (A → B → A) are accepted. | T-0002, ADR 0009 §8 | On create/update, walk the owner's dependency graph from the new `depends_on` ids and return 422 if it reaches the task itself. |
