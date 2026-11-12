import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import enrich_csv_gemini as script


def source(base, word, frequency='100'):
    return dict(zip(script.INPUT_COLUMNS, [base, word, 'B1', frequency]))


def enriched(row, text='existing content'):
    return script.EnrichedWordRow(**row, **{column: text for column in script.ENRICHED_COLUMNS})


class IncrementalEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.input = self.root / 'input'
        self.output = self.root / 'output'
        self.cache = self.root / 'cache'
        self.input.mkdir()
        self.output.mkdir()
        self.cache.mkdir()
        self.prompt = self.root / 'prompt.txt'
        self.prompt.write_text('Enrich these words.')
        self.args = ['--input-dir', str(self.input), '--output-dir', str(self.output),
                     '--cache-dir', str(self.cache),
                     '--prompt', str(self.prompt), '--env-file', str(self.root / 'no-env')]
        self.environment = patch.dict('os.environ', {script.API_KEY_ENV: 'test-key'})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def write_input(self, base, rows):
        (self.input / f'{base}.csv').write_text(script.rows_to_pipe_csv(script.INPUT_COLUMNS, rows))

    def read_output(self, base):
        with (self.output / f'{base}_enriched.csv').open() as handle:
            return list(csv.DictReader(handle, delimiter='|'))

    def test_only_missing_words_sent_and_existing_fields_preserved(self):
        self.write_input('gehen', [source('gehen', 'gehen', '999'), source('gehen', 'weggehen')])
        old = enriched(source('gehen', 'gehen'))
        script.write_enriched_csv(self.output / 'gehen_enriched.csv', [old])
        with patch.object(script, 'enrich_with_gemini', return_value=script.EnrichedCsv(
                rows=[enriched(source('gehen', 'weggehen'), 'new content')])) as api:
            self.assertEqual(script.main(self.args), 0)
        prompt = api.call_args.kwargs['prompt']
        self.assertIn('gehen|weggehen|B1|100', prompt)
        self.assertNotIn('gehen|gehen|B1|999', prompt)
        rows = self.read_output('gehen')
        self.assertEqual(rows[0]['word_freq'], '999')
        for column in script.ENRICHED_COLUMNS:
            self.assertEqual(rows[0][column], old.model_dump()[column])
        with patch.object(script, 'enrich_with_gemini') as api:
            self.assertEqual(script.main(self.args), 0)
            api.assert_not_called()

    def test_separate_cache_filters_extra_words_and_enriches_missing(self):
        self.write_input('retten', [source('retten', 'retten'), source('retten', 'erretten'),
                                    source('retten', 'hineinretten')])
        script.write_enriched_csv(self.cache / 'retten.csv', [
            enriched(source('retten', 'retten')), enriched(source('retten', 'rettbar')),
            enriched(source('retten', 'erretten'))])
        with patch.object(script, 'enrich_with_gemini', return_value=script.EnrichedCsv(
                rows=[enriched(source('retten', 'hineinretten'), 'new')])) as api:
            self.assertEqual(script.main(self.args), 0)
        self.assertIn('retten|hineinretten|B1|100', api.call_args.kwargs['prompt'])
        self.assertNotIn('retten|erretten|B1|100', api.call_args.kwargs['prompt'])
        self.assertEqual([row['word'] for row in self.read_output('retten')],
                         ['retten', 'erretten', 'hineinretten'])

    def test_reuses_other_families_and_omits_removed_words(self):
        self.write_input('sehen', [source('sehen', 'ansehen')])
        script.write_enriched_csv(self.output / 'other_enriched.csv', [enriched(source('other', 'ansehen'))])
        script.write_enriched_csv(self.output / 'sehen_enriched.csv', [enriched(source('sehen', 'Seherin'))])
        with patch.object(script, 'enrich_with_gemini') as api:
            self.assertEqual(script.main(self.args), 0)
            api.assert_not_called()
        self.assertEqual(self.read_output('sehen'), [enriched(source('sehen', 'ansehen')).model_dump()])

    def test_respects_capitalization_and_deduplicates_pending_across_families(self):
        self.write_input('a', [source('a', 'Leben'), source('a', 'leben')])
        self.write_input('b', [source('b', 'leben')])
        script.write_enriched_csv(self.output / 'old_enriched.csv', [enriched(source('old', 'Leben'))])
        with patch.object(script, 'enrich_with_gemini', return_value=script.EnrichedCsv(
                rows=[enriched(source('a', 'leben'))])) as api:
            self.assertEqual(script.main(self.args), 0)
            self.assertEqual(api.call_count, 1)
        self.assertEqual(self.read_output('b')[0]['word_base'], 'b')

    def test_incomplete_rows_are_retried_and_dry_run_does_not_write(self):
        self.write_input('a', [source('a', 'neu')])
        row = enriched(source('a', 'neu')).model_copy(update={'word_translation_en': ''})
        script.write_enriched_csv(self.output / 'a_enriched.csv', [row])
        before = (self.output / 'a_enriched.csv').read_bytes()
        with patch.object(script, 'enrich_with_gemini') as api:
            self.assertEqual(script.main(self.args + ['--dry-run']), 0)
            api.assert_not_called()
        self.assertEqual((self.output / 'a_enriched.csv').read_bytes(), before)
        with patch.object(script, 'enrich_with_gemini', return_value=script.EnrichedCsv(
                rows=[enriched(source('a', 'neu'), 'repaired')])) as api:
            self.assertEqual(script.main(self.args), 0)
            self.assertEqual(api.call_count, 1)

    def test_failed_later_batch_keeps_checkpoint_and_resume_skips_it(self):
        self.write_input('a', [source('a', 'eins'), source('a', 'zwei')])
        with patch.object(script, 'enrich_batch', side_effect=[
                [enriched(source('a', 'eins'))], script.EnrichmentError('failure')]):
            self.assertEqual(script.main(self.args + ['--batch-size', '1']), 1)
        self.assertEqual([r['word'] for r in self.read_output('a')], ['eins'])
        with patch.object(script, 'enrich_batch', return_value=[enriched(source('a', 'zwei'))]) as api:
            self.assertEqual(script.main(self.args), 0)
        self.assertEqual([r['word'] for r in api.call_args.args[-1]], ['zwei'])
        self.assertEqual(len(self.read_output('a')), 2)

    def test_standard_endpoint_schema_and_daily_quota_stop_without_retry(self):
        client = MagicMock()
        client.models.generate_content.return_value.text = script.EnrichedCsv(
            rows=[enriched(source('a', 'neu'))]).model_dump_json()
        with patch.object(script.genai, 'Client', return_value=client):
            result = script.enrich_with_gemini('test', script.DEFAULT_MODEL, 'prompt')
        self.assertEqual(result.rows[0].word, 'neu')
        self.assertIn('response_json_schema', client.models.generate_content.call_args.kwargs['config'])
        client.close.assert_called_once()

        class DailyQuotaError(Exception):
            code = 429
        client = MagicMock()
        client.models.generate_content.side_effect = DailyQuotaError('GenerateRequestsPerDayPerProjectPerModel-FreeTier')
        with patch.object(script.genai, 'Client', return_value=client), patch.object(script.time, 'sleep') as sleep:
            with self.assertRaises(script.EnrichmentQuotaError):
                script.enrich_batch('test', script.DEFAULT_MODEL, 'prompt', [source('a', 'neu')])
        self.assertEqual(client.models.generate_content.call_count, 1)
        sleep.assert_not_called()

    def test_valid_rows_saved_when_another_word_is_corrupted(self):
        self.write_input('a', [source('a', 'eins'), source('a', 'zwei')])
        response = script.EnrichedCsv(rows=[enriched(source('a', 'eins')),
                                            enriched(source('a', 'typo'))])
        with patch.object(script, 'enrich_with_gemini', return_value=response) as api:
            self.assertEqual(script.main(self.args), 1)
            self.assertEqual(api.call_count, 1)
        self.assertEqual([r['word'] for r in self.read_output('a')], ['eins'])
        response = script.EnrichedCsv(rows=[enriched(source('a', 'zwei'))])
        with patch.object(script, 'enrich_with_gemini', return_value=response) as api:
            self.assertEqual(script.main(self.args), 0)
            self.assertNotIn('a|eins|B1|100', api.call_args.kwargs['prompt'])


if __name__ == '__main__':
    unittest.main()
