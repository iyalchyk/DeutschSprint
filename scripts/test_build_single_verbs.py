import json
import tempfile
import unittest
from pathlib import Path

from build_single_verbs import candidates, family_words, related_words


class SingleVerbsTest(unittest.TestCase):
    def test_prefix_families_require_an_attested_base(self):
        words = {'bekommen', 'abbekommen', 'hinbekommen', 'hinzubekommen', 'beginnen'}
        self.assertEqual(related_words(words), {'bekommen', 'abbekommen', 'hinbekommen', 'hinzubekommen'})

    def test_local_candidates_and_family_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dereko = root / 'dereko'
            dereko.write_text('startet\tstarten\tVVFIN\t10\nHaus\tHaus\tNN\t5\n', encoding='utf-8')
            api = root / 'api.json'
            api.write_text(json.dumps({'data': [
                {'german': 'beginnen', 'pos': 'verb'},
                {'german': 'laufen', 'pos': 'verb'},
                {'german': 'Haus', 'pos': 'noun'},
            ]}), encoding='utf-8')
            (root / 'gehen.csv').write_text('word_base|word|word_level|word_freq\ngehen|laufen|A1|1\n', encoding='utf-8')
            output = root / '_single_verbs.csv'
            output.write_text('word_base|word|word_level|word_freq\nbeginnen|beginnen|A1|1\n', encoding='utf-8')
            self.assertEqual(candidates(dereko, api) - family_words(root, output), {'starten', 'beginnen'})


if __name__ == '__main__':
    unittest.main()
