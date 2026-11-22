#!/usr/bin/env python3
# Copyright 2026 Duck Apps Contributor
# If you have any questions, suggestions, or other inquiries, please email Eltavine <me@eltavine.com>.
# SPDX-License-Identifier: Apache-2.0
"""Advance the fixed Nightly channel after its immutable archive is public and verified."""
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import tempfile

from nightly_release import (
    CHANNEL_TAG, check_file, gh, require_channel, require_complete, require_immutable, safe_name,
    validate_manifest, validate_tag, verify_ref,
)


def download(repo, tag, name, directory):
    safe_name(name)
    directory.mkdir(parents=True, exist_ok=True)
    subprocess.run(['gh', 'release', 'download', tag, '--repo', repo,
                    '--pattern', name, '--dir', str(directory), '--clobber'], check=True)
    return directory / name


def ordering(manifest):
    version = manifest.get('versionCode')
    if type(version) is not int or version <= 0:
        raise ValueError('Channel manifest has an invalid version code')
    instant = datetime.fromisoformat(manifest['builtAtUtc'].replace('Z', '+00:00'))
    if instant.utcoffset() is None:
        raise ValueError('Channel build time has no timezone')
    return version, instant


def write_pointer(repo, path, previous, directory):
    try:
        subprocess.run(['gh', 'release', 'upload', CHANNEL_TAG, str(path), '--clobber', '--repo', repo], check=True)
        uploaded = download(repo, CHANNEL_TAG, 'update.json', directory / 'verify-pointer')
        if uploaded.read_bytes() != path.read_bytes():
            raise ValueError('Published channel manifest differs from the prepared manifest')
    except Exception:
        if previous is not None:
            subprocess.run(['gh', 'release', 'upload', CHANNEL_TAG, str(previous), '--clobber', '--repo', repo], check=True)
        raise


def advance(repo, tag, sha, directory):
    validate_tag(tag, sha)
    release = require_channel(repo, allow_incomplete=True)
    verify_ref(repo, tag, sha)
    archive_release = gh('api', f'repos/{repo}/releases/tags/{tag}')
    require_complete(archive_release, tag)
    require_immutable(archive_release)
    archive_path = download(repo, tag, 'update.json', directory / 'archive')
    archive = json.loads(archive_path.read_text(encoding='utf-8'))
    validate_manifest(archive, repo, tag, sha)
    previous = None
    if any(item.get('state') == 'uploaded' and item.get('size', 0) > 0 for item in release['assets']):
        previous = download(repo, CHANNEL_TAG, 'update.json', directory / 'previous')
        old = json.loads(previous.read_text(encoding='utf-8'))
        if ordering(old) > ordering(archive):
            return False
    for key in ['apk', 'sdk']:
        asset = archive[key]
        path = download(repo, tag, asset['name'], directory / 'archive')
        check_file(path, asset)
    unchanged = previous is not None and previous.read_bytes() == archive_path.read_bytes()
    if not unchanged:
        write_pointer(repo, archive_path, previous, directory)
    # The fixed release record and tag are never edited: only its JSON asset changes.
    if require_channel(repo)['id'] != release['id']:
        raise ValueError('The channel release identity changed during publication')
    return not unchanged


def main():
    repo, sha, tag = os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_SHA'], os.environ['NIGHTLY_TAG']
    directory = Path(tempfile.mkdtemp(prefix='nightly-channel-', dir=os.environ['RUNNER_TEMP']))
    advanced = advance(repo, tag, sha, directory)
    with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as output:
        output.write(f'advanced={str(advanced).lower()}\n')


if __name__ == '__main__':
    main()
