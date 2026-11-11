"""Personal OS command line.

    uv run python -m tools.pos export --data-dir <dir> --out <file.zip>
    uv run python -m tools.pos import --in <file.zip> --data-dir <empty dir>

Exit code 0 on success, 1 when the package or target is rejected (message on stderr).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from apps.hub.backup.service import BackupError, export_data, import_data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pos", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    export_cmd = commands.add_parser("export", help="write all Hub data to a zip package")
    export_cmd.add_argument("--data-dir", type=Path, required=True)
    export_cmd.add_argument("--out", type=Path, required=True)

    import_cmd = commands.add_parser("import", help="restore a package into an empty dir")
    import_cmd.add_argument("--in", dest="package", type=Path, required=True)
    import_cmd.add_argument("--data-dir", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            manifest = export_data(args.data_dir, args.out)
            schema = manifest.schema_version
            action = f"exported to {args.out}"
        else:
            result = import_data(args.package, args.data_dir)
            manifest = result.manifest
            before, after = manifest.schema_version, result.schema_version
            schema = before if before == after else f"{before} -> {after} (migrated)"
            action = f"imported into {args.data_dir}"
    except BackupError as exc:
        print(f"pos {args.command}: {exc}", file=sys.stderr)
        return 1
    rows = sum(manifest.row_counts.values())
    print(f"{action}: schema {schema}, {rows} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
