"""Synthetic archive boundary tests. No test here qualifies or executes a daemon."""
import dataclasses
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
import zipfile

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('native_build_input', HERE / 'acquire-native-build.py')
build = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = build
SPEC.loader.exec_module(build)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


class ArchiveBoundaries(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        for file in self.root.rglob('*'):
            if file.is_dir():
                file.chmod(0o700)
        self.temporary.cleanup()

    def fixture(self, *, special=None, duplicate=False, extra=False, missing=False,
                bad_mode=False, qualification=False, manifest_shape=None):
        expected = build.load_expected()
        content = b'synthetic non-executable build bytes'
        row = {'path': 'entry.txt', 'size': len(content),
               'sha256': sha(content), 'mode': 0o666 if bad_mode else 0o444}
        manifest = {'schemaVersion': 2, 'profile': 'enclosing-daemon-v2',
                    'builtinPlugins': list(build.BUILTINS), 'distributionBuildId': 'synthetic-only',
                    'files': [row]}
        raw_manifest = encoded(manifest if manifest_shape is None else manifest_shape)
        evidence = {'schemaVersion': 1, 'kind': 'paseo-daemon-build-input-evidence',
                    'qualification': qualification, 'source': {'commit': expected.evaluator_commit},
                    'build': {'repository': expected.repository, 'runId': str(expected.run_id),
                              'attempt': str(expected.run_attempt)},
                    'manifestSha256': sha(raw_manifest), 'distributionBuildId': 'synthetic-only'}
        raw_evidence = encoded(evidence)
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w') as tar:
            directory = tarfile.TarInfo('qualified-daemon')
            directory.type, directory.mode = tarfile.DIRTYPE, 0o555
            tar.addfile(directory)

            def regular(name, value, mode=0o444):
                item = tarfile.TarInfo(name)
                item.size, item.mode = len(value), mode
                tar.addfile(item, io.BytesIO(value))

            if not missing:
                regular('qualified-daemon/entry.txt', content, row['mode'])
            if duplicate:
                regular('qualified-daemon/entry.txt', content)
            if extra:
                regular('qualified-daemon/undeclared.txt', content)
            if special:
                item = tarfile.TarInfo(special[0])
                item.type, item.linkname = special[1], '/outside'
                tar.addfile(item)
            regular('qualified-daemon.manifest.json', raw_manifest)
            regular('qualified-daemon.build-evidence.json', raw_evidence)
        tar_bytes = buffer.getvalue()
        archive = self.root / 'input.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
            zipped.writestr('qualified-daemon-build.tar', tar_bytes)
            zipped.writestr('SHA256SUMS', sha(tar_bytes) + '  qualified-daemon-build.tar\n')
        expected = dataclasses.replace(expected, archive_sha256=sha(archive.read_bytes()),
                                       tar_sha256=sha(tar_bytes), manifest_sha256=sha(raw_manifest),
                                       evidence_sha256=sha(raw_evidence))
        return archive, expected

    def inspect(self, **kwargs):
        archive, expected = self.fixture(**kwargs)
        return build.inspect_archive(archive, self.root, expected)

    def test_exact_bytes_materialize_without_execution_or_qualification(self):
        tar_path, manifest, evidence = self.inspect()
        self.assertIs(evidence['qualification'], False)
        destination = self.root / 'unpacked'
        build.materialize(tar_path, destination)
        self.assertEqual((destination / 'qualified-daemon/entry.txt').read_bytes(),
                         b'synthetic non-executable build bytes')
        self.assertEqual((destination / 'qualified-daemon').stat().st_mode & 0o777, 0o555)
        with self.assertRaises(FileExistsError):
            build.materialize(tar_path, destination)

    def test_links_special_files_and_traversal_refuse_before_materialization(self):
        for name, kind in [('qualified-daemon/link', tarfile.SYMTYPE),
                           ('qualified-daemon/hard', tarfile.LNKTYPE),
                           ('qualified-daemon/fifo', tarfile.FIFOTYPE),
                           ('../escape', tarfile.REGTYPE)]:
            with self.subTest(name=name):
                archive, expected = self.fixture(special=(name, kind))
                trial = self.root / name.replace('/', '_').replace('.', '_')
                trial.mkdir()
                with self.assertRaises(build.ContractError):
                    build.inspect_archive(archive, trial, expected)
                self.assertFalse((self.root / 'escape').exists())

    def test_duplicate_extra_missing_and_writable_files_refuse(self):
        for case in ('duplicate', 'extra', 'missing', 'bad_mode'):
            with self.subTest(case=case):
                archive, expected = self.fixture(**{case: True})
                trial = self.root / case
                trial.mkdir()
                with self.assertRaises(build.ContractError):
                    build.inspect_archive(archive, trial, expected)

    def test_build_archive_cannot_claim_runtime_qualification(self):
        with self.assertRaises(build.ContractError):
            self.inspect(qualification=True)

    def test_malformed_metadata_has_bounded_contract_failure(self):
        with self.assertRaises(build.ContractError):
            self.inspect(manifest_shape=[])

    def test_all_protected_digests_are_checked(self):
        archive, expected = self.fixture()
        for field in ('archive_sha256', 'tar_sha256', 'manifest_sha256', 'evidence_sha256'):
            with self.subTest(field=field):
                trial = self.root / field
                trial.mkdir()
                wrong = dataclasses.replace(expected, **{field: '0' * 64})
                with self.assertRaises(build.ContractError):
                    build.inspect_archive(archive, trial, wrong)

    def test_member_and_expansion_bounds(self):
        archive, expected = self.fixture()
        for name in ('MAX_MEMBERS', 'MAX_TAR'):
            original = getattr(build, name)
            try:
                setattr(build, name, 1)
                trial = self.root / name
                trial.mkdir()
                with self.assertRaises(build.ContractError):
                    build.inspect_archive(archive, trial, expected)
            finally:
                setattr(build, name, original)


if __name__ == '__main__':
    unittest.main()
