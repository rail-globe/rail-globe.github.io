import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from owned_output import require_owned, atomic_json


class OwnedOutputTests(unittest.TestCase):
    def test_linked_file_is_rejected_before_source_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'
            source.write_text('original')
            out = root / 'copy'
            out.mkdir()
            (out / 'generated.json').symlink_to(source)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                require_owned(out, ['generated.json'])
            self.assertEqual(source.read_text(), 'original')

    def test_linked_parent_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source'
            source.mkdir()
            out = root / 'copy'
            out.mkdir()
            (out / 'tiles').symlink_to(source, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                require_owned(out, ['tiles/cn.json'])

    def test_regular_owned_file_and_new_target_are_allowed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'existing').write_text('owned')
            require_owned(root, ['existing', 'new'])

    def test_parent_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'escapes'):
                require_owned(Path(folder), ['../outside'])

    def test_invalid_new_json_keeps_previous_complete_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'data.json'
            atomic_json(target, {'valid':True})
            before = target.read_bytes()
            with self.assertRaises(ValueError):
                atomic_json(target, {'invalid':float('nan')})
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])
