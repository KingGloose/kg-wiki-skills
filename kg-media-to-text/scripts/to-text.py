#!/usr/bin/env python3
"""Thin CLI bridge for Node workflows that need the Python document/ASR backends."""
from __future__ import annotations

import argparse
import json
import sys

from media_to_text import MediaToTextError, SourceKind, to_text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--model")
    parser.add_argument("--kind", choices=["audio", "video"])
    parser.add_argument("--language")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    kind = SourceKind(args.kind) if args.kind else None
    try:
        result = to_text(args.source, kind=kind, model=args.model, language=args.language)
    except MediaToTextError as error:
        print(f"[错误] {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"text": result.text, "backend": result.backend,
                          "metadata": result.metadata}, ensure_ascii=False))
    else:
        print(result.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
