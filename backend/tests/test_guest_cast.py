"""Run from backend with python -m unittest discover -s tests."""
import base64
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi import HTTPException
from PIL import Image

from guest_cast import guest_actors, store_portrait
from production import line_voices


class CastingFixture:
    tts_key = "offline-test"

    def has_voice(self, cid):
        return cid == 'mano'

    def outfit(self, owner, outfit):
        if (owner, outfit) == ('mano', 'stand/default'):
            return {'id': outfit}


class GuestCastingTests(unittest.TestCase):
    def setUp(self):
        self.adapter = CastingFixture()
        self.doc = {
            'outline': {'guests': [{'id': 'guest_1', 'name': '妹妹'}, {'id': 'guest_2', 'name': '父亲'}]},
            'guest_cast': {
                'guest_1': {'voice_id': 'voice-a', 'portrait': 'test-image'},
                'guest_2': {'outfit_owner': 'mano', 'outfit': 'stand/default'},
            },
        }

    def test_chorus_keeps_only_voiced_tracks_and_original_guest_ids(self):
        line = {'speaker': 'mano', 'speakers': ['mano', 'guest_1', 'guest_2'], 'id': '0-1'}
        tracks = line_voices(line, self.doc, self.adapter)
        self.assertEqual([t['id'] for t in tracks], ['0-1~mano', '0-1~guest_1'])
        self.assertEqual(tracks[1]['guest_voice'], 'voice-a')
        self.assertNotIn('guest_voice', line)
        self.assertEqual(line_voices({'id': '0-2', 'speaker': 'guest_1'}, {}, self.adapter), [])

    def test_guest_names_survive_borrowing_an_outfit(self):
        sister, father = guest_actors(self.doc, self.adapter)
        self.assertEqual((sister['name'], sister['portrait']), ('妹妹', 'test-image'))
        self.assertEqual((father['name'], father['stand']['id']), ('父亲', 'stand/default'))

    def test_uploaded_portrait_keeps_transparency_and_reuses_identical_file(self):
        buf = BytesIO()
        Image.new('RGBA', (10, 20), (255, 0, 0, 128)).save(buf, 'PNG')
        encoded = base64.b64encode(buf.getvalue()).decode()
        with TemporaryDirectory() as tmp:
            path = Path(tmp)
            digest = store_portrait(encoded, path)
            self.assertEqual(store_portrait(encoded, path), digest)
            with Image.open(path / (digest + '.png')) as image:
                self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 128))
            with self.assertRaises(HTTPException):
                store_portrait('invalid', path)
            self.assertEqual(len(list(path.iterdir())), 1)
