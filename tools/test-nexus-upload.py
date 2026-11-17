#!/usr/bin/env python3
"""Check the boundary between tested GitHub release files and Nexus publishing."""
import hashlib
import importlib.util
import io
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('nexus_upload', ROOT / 'tools/prepare-nexus-upload.py')
nexus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nexus)
spec = importlib.util.spec_from_file_location('linux_package', ROOT / 'tools/package-linux.py')
linux_package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(linux_package)

VERSION = '0.1.0-alpha.11'


def write_zip(path, entries):
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in entries.items():
            archive.writestr(name, data)


def write_tar(path, entries):
    """entries: name -> (bytes, mode), or None for a directory."""
    with tarfile.open(path, 'w:gz') as archive:
        for name, entry in entries.items():
            info = tarfile.TarInfo(name)
            info.mtime = 1_700_000_000
            if entry is None:
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                archive.addfile(info)
            else:
                data, info.mode = entry
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))


def write_linux_zip(path, entries):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name, entry in entries.items():
            file = root / name
            if entry is None:
                file.mkdir(parents=True, exist_ok=True)
            else:
                data, mode = entry
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(data)
                file.chmod(mode)
        linux_package.package_linux(root / 'linux-x64', path)


class NexusUpload(unittest.TestCase):
    def setUp(self):
        self.commit = 'a' * 40
        self.tag = 'v' + VERSION
        self.release = {'tagName': self.tag, 'isDraft': False, 'isPrerelease': True}
        self.run = {'path': '.github/workflows/build.yml', 'event': 'push', 'head_sha': self.commit,
                    'head_branch': self.tag, 'status': 'completed', 'conclusion': 'success'}

    def release_files(self, directory, windows=None, linux=None, legacy=False):
        names = nexus.files(VERSION, {f'PenguTEX-{VERSION}-linux-x64.tar.gz'} if legacy else None)
        write_zip(directory / names['windows'], windows or {
            'win-x64/PenguTEX.Desktop.exe': b'MZ desktop', 'win-x64/PenguTEX.exe': b'MZ cli',
            'win-x64/pengutex_bc7.dll': b'MZ bc7', 'win-x64/VERSION': VERSION + '\n'})
        (write_tar if legacy else write_linux_zip)(directory / names['linux'], linux or {
            'linux-x64': None, 'linux-x64/PenguTEX': (b'cli', 0o755), 'linux-x64/PenguTEX.Desktop': (b'desktop', 0o755),
            'linux-x64/libpengutex_bc7.so': (b'ELF', 0o755), 'linux-x64/install-desktop.sh': (b'#!/bin/sh\n', 0o755),
            'linux-x64/VERSION': ((VERSION + '\n').encode(), 0o644), 'linux-x64/docs': None,
            'linux-x64/docs/CLI.md': (b'# CLI\n', 0o644)})
        sums = ''.join(f'{hashlib.sha256((directory / name).read_bytes()).hexdigest()}  {name}\n'
                       for name in names.values())
        (directory / 'SHA256SUMS').write_text(sums + 'f' * 64 + f'  PenguTEX-{VERSION}-source.tar.gz\n')
        return names

    def test_accepts_published_releases_and_pre_releases(self):
        nexus.validate_release(self.tag, self.release, self.commit, [self.run])
        nexus.validate_release('v0.2.0', {'tagName': 'v0.2.0', 'isDraft': False, 'isPrerelease': False}, self.commit,
                               [{**self.run, 'head_branch': 'master'}, {**self.run, 'head_branch': 'v0.2.0'}])

    def test_rejects_tags_that_are_not_versions(self):
        for tag in ('main', '0.6.0', 'v0.6', 'v0.6.0+build', 'v01.6.0', '--help', 'v0.6.0\n', 'v0.6.0-'):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                nexus.release_version(tag)

    def test_requires_a_published_release_for_the_tag(self):
        for change in ({'isDraft': True}, {'isPrerelease': False}, {'tagName': 'v0.1.0-alpha.10'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                nexus.validate_release(self.tag, {**self.release, **change}, self.commit, [self.run])

    def test_requires_a_successful_build_of_the_tag(self):
        changes = ({'path': '.github/workflows/nexus.yml'}, {'event': 'workflow_dispatch'}, {'head_sha': 'b' * 40},
                   {'head_branch': 'master'}, {'status': 'in_progress'}, {'conclusion': 'failure'})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                nexus.validate_release(self.tag, self.release, self.commit, [{**self.run, **change}])
        with self.assertRaises(ValueError):
            nexus.validate_release(self.tag, self.release, self.commit, [])

    def test_verifies_checksums_and_package_versions(self):
        for platform in ('windows', 'linux'):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                names = self.release_files(directory)
                packages = nexus.verify_downloads(directory, VERSION)
                self.assertEqual({key: directory / name for key, name in names.items()}, packages)
                with (directory / names[platform]).open('ab') as stream:
                    stream.write(b'changed after release')
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    nexus.verify_downloads(directory, VERSION)

    def test_prefers_published_zip_and_accepts_older_tarball_releases(self):
        current = f'PenguTEX-{VERSION}-linux-x64.zip'
        legacy = f'PenguTEX-{VERSION}-linux-x64.tar.gz'
        self.assertEqual(current, nexus.files(VERSION)['linux'])
        self.assertEqual(current, nexus.files(VERSION, {current, legacy})['linux'])
        self.assertEqual(legacy, nexus.files(VERSION, {legacy})['linux'])
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            self.release_files(directory, legacy=True)
            self.assertEqual(directory / legacy, nexus.verify_downloads(directory, VERSION)['linux'])

    def test_rejects_packages_of_another_version_or_missing_programs(self):
        cases = (
            ({'windows': {'win-x64/PenguTEX.Desktop.exe': b'MZ', 'win-x64/PenguTEX.exe': b'MZ', 'win-x64/pengutex_bc7.dll': b'MZ',
                          'win-x64/VERSION': '0.1.0-alpha.10\n'}}, 'another version'),
            ({'windows': {'win-x64/PenguTEX.exe': b'MZ', 'win-x64/pengutex_bc7.dll': b'MZ', 'win-x64/VERSION': VERSION}}, 'missing'),
            ({'windows': {'win-x64/PenguTEX.Desktop.exe': b'MZ', 'win-x64/PenguTEX.exe': b'MZ', 'win-x64/VERSION': VERSION}}, 'missing'),
            ({'linux': {'linux-x64/PenguTEX': (b'', 0o755), 'linux-x64/PenguTEX.Desktop': (b'', 0o755),
                        'linux-x64/libpengutex_bc7.so': (b'', 0o755), 'linux-x64/VERSION': (b'0.1.0-alpha.10\n', 0o644)}},
             'another version'),
            ({'linux': {'linux-x64/PenguTEX': (b'', 0o755), 'linux-x64/PenguTEX.Desktop': (b'', 0o755),
                        'linux-x64/VERSION': ((VERSION + '\n').encode(), 0o644)}}, 'missing'),
            ({'linux': {'linux-x64/PenguTEX': (b'', 0o755), 'linux-x64/PenguTEX.Desktop': (b'', 0o644),
                        'linux-x64/libpengutex_bc7.so': (b'', 0o755), 'linux-x64/VERSION': (VERSION.encode(), 0o644)}},
             'not executable'),
        )
        for change, message in cases:
            with self.subTest(change=list(change)), tempfile.TemporaryDirectory() as tmp:
                self.release_files(Path(tmp), **change)
                with self.assertRaisesRegex(ValueError, message):
                    nexus.verify_downloads(Path(tmp), VERSION)

    def test_linux_zip_keeps_contents_and_executable_permissions(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                names = self.release_files(directory, legacy=legacy)
                original = directory / names['linux']
                before = original.read_bytes()
                verified = nexus.verify_downloads(directory, VERSION)['linux']
                output = nexus.repack_linux(verified, directory / 'linux.zip') if legacy else verified
                self.assertEqual(before, original.read_bytes())
                with zipfile.ZipFile(output) as archive:
                    self.assertIsNone(archive.testzip())
                    modes = {info.filename: info.external_attr >> 16 & 0o777 for info in archive.infolist()}
                    self.assertEqual(b'#!/bin/sh\n', archive.read('linux-x64/install-desktop.sh'))
                self.assertEqual(0o755, modes['linux-x64/PenguTEX'])
                self.assertEqual(0o755, modes['linux-x64/PenguTEX.Desktop'])
                self.assertEqual(0o755, modes['linux-x64/install-desktop.sh'])
                self.assertEqual(0o644, modes['linux-x64/VERSION'])
                self.assertIn('linux-x64/docs/', modes)
                # What a user's extractor does with it.
                if shutil.which('unzip'):
                    subprocess.run(['unzip', '-q', str(output), '-d', str(directory / 'out')], check=True)
                    launcher = directory / 'out/linux-x64/PenguTEX.Desktop'
                    self.assertEqual(0o755, launcher.stat().st_mode & 0o777)
                    self.assertEqual(0o644, (directory / 'out/linux-x64/VERSION').stat().st_mode & 0o777)
                    self.assertTrue((directory / 'out/linux-x64/docs/CLI.md').is_file())
                if legacy:
                    with self.assertRaises(FileExistsError):
                        nexus.repack_linux(original, output)

    def test_rebuilding_zip_removes_stale_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            output = directory / 'linux.zip'
            write_linux_zip(output, {'linux-x64/old.txt': (b'old', 0o644)})
            write_linux_zip(output, {'linux-x64/new.txt': (b'new', 0o644)})
            with zipfile.ZipFile(output) as archive:
                self.assertNotIn('linux-x64/old.txt', archive.namelist())
                self.assertEqual(b'new', archive.read('linux-x64/new.txt'))

    def test_linux_packager_refuses_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            payload = directory / 'linux-x64'
            payload.mkdir()
            (payload / 'link').symlink_to('/etc/passwd')
            with self.assertRaisesRegex(ValueError, 'Unsupported entry'):
                linux_package.package_linux(payload, directory / 'linux.zip')

    def test_linux_zip_refuses_links_and_paths_outside_the_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_tar(directory / 'outside.tar.gz', {'linux-x64/../evil': (b'x', 0o644)})
            write_tar(directory / 'other.tar.gz', {'elsewhere/file': (b'x', 0o644)})
            with tarfile.open(directory / 'link.tar.gz', 'w:gz') as archive:
                info = tarfile.TarInfo('linux-x64/link')
                info.type, info.linkname = tarfile.SYMTYPE, '/etc/passwd'
                archive.addfile(info)
            for name in ('outside', 'other', 'link'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    nexus.repack_linux(directory / f'{name}.tar.gz', directory / f'{name}.zip')

    def test_changelog_is_the_versions_section_one_line_per_entry(self):
        changelog = ('# Changelog\n\n## [Unreleased]\n\n- Later.\n\n'
                     f'## [{VERSION}] - 2026-11-17\n\nRebuild existing outputs once.\n\n'
                     '- Added **native BC7** encoding for\n  mip completion.\n- Fixed `prune-cache` and the\n'
                     '  [CLI guide](docs/CLI.md).\n\n## [0.1.0-alpha.10] - 2026-10-30\n\n- Older.\n')
        section = nexus.changelog_section(changelog, VERSION)
        self.assertEqual(['Rebuild existing outputs once.', 'Added native BC7 encoding for mip completion.',
                          'Fixed prune-cache and the CLI guide.'], nexus.plain_changelog(section).splitlines())
        with self.assertRaises(ValueError):
            nexus.changelog_section(changelog, '0.2.0')

if __name__ == '__main__':
    unittest.main()
