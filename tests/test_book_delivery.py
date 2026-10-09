import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import test_audiobook
from test_audiobook import wav, audiobook, atomic_json
from book_pdf import build_pdf
import book_video


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_audiobook.AudiobookTests()
        self.fixture.setUp()
        self.job, self.root = self.fixture.job, self.fixture.root

    def tearDown(self):
        self.fixture.tearDown()

    def narrate(self):
        audiobook.prepare(self.job, audiobook.DEFAULTS, [1, 2])
        audiobook.run(self.job, lambda text, settings: wav())

    def test_pdf_contains_all_final_text_and_updates_after_edit(self):
        output = build_pdf(self.job)
        self.assertTrue(output.read_bytes().startswith(b'%PDF'))
        previous = audiobook.read(self.job / '08_Memory/pdf.json')['fingerprint']
        if shutil.which('pdftotext'):
            text = subprocess.check_output(['pdftotext', str(output), '-'], encoding='utf-8')
            self.assertEqual(text.count('She heard the sea.'), 180)
            self.assertIn('At dawn she returned.', text)
            self.assertIn('Contents', text)
        atomic_json(self.job / '08_Memory/chapter_02.json', {'title':'Return','prose_content':'An edited ending.'})
        build_pdf(self.job)
        self.assertNotEqual(audiobook.read(self.job / '08_Memory/pdf.json')['fingerprint'], previous)

    def test_video_requires_narration_before_build_and_validation_before_render(self):
        with self.assertRaisesRegex(ValueError, 'narration'):
            book_video.prepare(self.job, {'chapters':[1]})
        self.narrate()
        book_video.prepare(self.job, {'chapters':[1,2]})
        with self.assertRaises(ValueError):
            book_video.prepare(self.job, {'action':'render'})

    def test_whole_book_composition_covers_every_word_and_all_narration(self):
        self.narrate()
        atomic_json(self.job / '08_Memory/psychology.json', {'characters':[{'name':'Ada', 'voice':'Quiet'}]})
        book_video.prepare(self.job, {'chapters':[1,2]})
        state = audiobook.read(self.job / 'film/state.json')
        book_video.build(self.job, state)
        storyboard = audiobook.read(self.job / 'film/storyboard.json')
        total = sum(c['duration'] for c in audiobook.status(self.job)['tracks'].values())
        self.assertAlmostEqual(storyboard['duration'], total)
        expected = ' '.join(c['prose'] for c in audiobook.studio_data(self.job)['chapters']).split()
        actual = ' '.join(c['text'] for c in storyboard['cards']).split()
        self.assertEqual(actual, expected)
        self.assertEqual(storyboard['cast'][0]['name'], 'Ada')
        svg = (self.job / 'film/assets/character-0.svg').read_text()
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', svg)
        self.assertEqual(len(list((self.job / 'film/assets').glob('chapter-*.wav'))), 2)
        self.assertIn('data-composition-src', (self.job / 'film/index.html').read_text())

    def test_video_revision_is_invalidated_when_book_changes(self):
        self.narrate()
        book_video.prepare(self.job, {'chapters':[2]})
        atomic_json(self.job / '08_Memory/chapter_02.json', {'title':'Return','prose_content':'Different ending.'})
        self.assertEqual(book_video.status(self.job)['status'], 'stale')

    def test_failed_validation_cannot_offer_a_render(self):
        self.narrate()
        book_video.prepare(self.job, {'chapters':[2]})
        with patch('book_video.subprocess.run', return_value=Mock(returncode=1, stdout='failed', stderr='')):
            with self.assertRaisesRegex(RuntimeError, 'validation failed'):
                book_video.run(self.job)
        self.assertFalse(book_video.status(self.job)['validated'])
        with self.assertRaises(ValueError):
            book_video.prepare(self.job, {'action':'render'})


if __name__ == '__main__':
    unittest.main()
