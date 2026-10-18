"""Import a manually reviewed JSON dossier; no credentials or remote fetching."""
import argparse
import json
from pathlib import Path

from future_transformation import import_document, PILOT_PATH


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', type=Path, nargs='?')
    parser.add_argument('--pilots', action='store_true', help='Register bundled official pilot facts')
    args = parser.parse_args()
    if not args.file and not args.pilots:
        parser.error('file or --pilots required')
    documents = json.loads((PILOT_PATH if args.pilots else args.file).read_text(encoding='utf-8'))
    for document in documents if isinstance(documents, list) else [documents]:
        revision = import_document(document)
        print(f'검증 자료 저장 완료: {revision}')


if __name__ == '__main__':
    main()
