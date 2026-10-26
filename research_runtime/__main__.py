"""Explicit offline acceptance; output goes only to the caller's stdout."""
import argparse
import json
from pathlib import Path
import sys

from .inference import read_json_bytes, run_acceptance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--request', required=True, type=Path)
    args = parser.parse_args()
    try:
        with args.request.open('rb') as stream:
            request = read_json_bytes(stream.read(131073))
        result = run_acceptance(request, args.manifest, args.manifest_sha256)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except Exception as error:
        # Do not print exception messages: parsers and estimators can quote data.
        print(json.dumps({'status': 'REJECTED', 'errorType': type(error).__name__,
                          'clinicalUse': False}), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
