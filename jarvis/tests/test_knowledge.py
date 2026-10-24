import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agent.data import DataSource, selected_source
from agent.vault import KnowledgeIndex, MAX_FILE_BYTES
from data.generate_demo import generate

class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def index(self):
        return KnowledgeIndex(DataSource(self.root, True)).build()

    def test_index_search_and_source_unchanged(self):
        path = self.write('Robotics/rover.md', '# Rover\nESP32 obstacle sensor')
        before = path.read_bytes()
        index = self.index()
        self.assertEqual(len(index.documents), 1)
        self.assertEqual(index.search('esp32 sensor')[0]['citation'], 'Robotics/rover.md:2')
        self.assertEqual(index.search('missing'), [])
        self.assertEqual(index.search(''), [])
        self.assertEqual(path.read_bytes(), before)

    def test_links_aliases_paths_and_shortest_path(self):
        self.write('a.md', '[[b|label]] [[missing]] [[a]]')
        self.write('b.md', '[[sub/c#Heading]]')
        self.write('sub/c.md', 'hello')
        index = self.index()
        self.assertEqual(index.edges, {('a.md', 'b.md'), ('b.md', 'sub/c.md')})
        self.assertEqual(index.shortest_path('a.md', 'sub/c.md'), ['a.md', 'b.md', 'sub/c.md'])
        self.assertEqual(index.hubs()[0], ('b.md', 2))

    def test_ambiguous_links_not_invented(self):
        self.write('a.md', '[[same]]')
        self.write('one/same.md', 'one')
        self.write('two/same.md', 'two')
        self.assertFalse(self.index().edges)

    def test_skips_and_boundaries(self):
        self.write('.git/private.md', 'private')
        self.write('node_modules/private.md', 'private')
        self.write('big.txt', 'x' * (MAX_FILE_BYTES + 1))
        self.write('binary.txt', '\x00binary')
        self.write('unsupported.py', 'pass')
        self.write('sample.pdf', 'not a real PDF')
        self.write('valid.txt', 'safe')
        index = self.index()
        self.assertEqual(set(index.documents), {'valid.txt'})
        self.assertEqual(len(index.skipped), 4)

    def test_symlink_escape(self):
        with tempfile.TemporaryDirectory() as outside:
            secret = Path(outside) / 'secret.md'
            secret.write_text('private')
            try:
                (self.root / 'escape.md').symlink_to(secret)
                (self.root / 'escape_dir').symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest('Symlinks unavailable on this host')
            self.assertFalse(self.index().documents)

    def test_demo_default_isolation(self):
        with patch.dict(os.environ, {}, clear=True), patch('pathlib.Path.home', side_effect=AssertionError('real home accessed')):
            source = selected_source()
            self.assertTrue(source.demo)
            self.assertEqual(source.root.name, 'demo')

    def test_real_requires_explicit_approval(self):
        with patch.dict(os.environ, {'JARVIS_DEMO': '0'}):
            with self.assertRaises(PermissionError):
                selected_source()
            with patch('pathlib.Path.home', return_value=self.root):
                source = selected_source(approve_real=True)
                self.assertEqual(source.root, self.root / 'Documents' / 'JARVIS_KNOWLEDGE')
                self.assertFalse(source.demo)

    def test_invalid_mode(self):
        with patch.dict(os.environ, {'JARVIS_DEMO': 'maybe'}):
            with self.assertRaises(ValueError):
                selected_source()

    def test_fixtures_repeatable_and_non_destructive(self):
        first, second = self.root / 'first', self.root / 'second'
        self.assertEqual(generate(first), 13)
        self.assertEqual(generate(second), 13)
        for path in first.rglob('*.md'):
            self.assertEqual(path.read_bytes(), (second / path.relative_to(first)).read_bytes())
        sample = next(first.rglob('*.md'))
        sample.write_text('preserve owner edit')
        self.assertEqual(generate(first), 0)
        self.assertEqual(sample.read_text(), 'preserve owner edit')

    def test_missing_directory_reported(self):
        index = KnowledgeIndex(DataSource(self.root / 'absent', False)).build()
        self.assertFalse(index.documents)
        self.assertTrue(index.warnings)

if __name__ == '__main__':
    unittest.main()
