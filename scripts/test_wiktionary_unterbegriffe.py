import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts.wiktionary_unterbegriffe import extract_unterbegriffe, frequency_verbs, build_rows, is_prefixed_verb, main


class ExtractUnterbegriffeTests(unittest.TestCase):
    def test_only_accepts_a_listed_prefix(self):
        for word, base, expected in [("umgehen", "gehen", True), ("pflegen", "legen", False),
                                     ("gleiten", "leiten", False), ("zurücklegen", "legen", True),
                                     ("gehen", "gehen", False), ("umzugehen", "gehen", False)]:
            with self.subTest(word=word):
                self.assertEqual(is_prefixed_verb(word, base), expected)
        self.assertEqual(extract_unterbegriffe("{{Unterbegriffe}}\n:[[pflegen]], [[ablegen]]", "legen"), ["ablegen"])

    def test_combines_sections_even_when_wortbildungen_is_larger(self):
        text = """== tauchen ({{Sprache|Deutsch}}) ==
{{Unterbegriffe}}
:[1] [[abtauchen]], [[antauchen]], [[auftauchen]]

{{Beispiele}}
:[[schwimmen]]

{{Wortbildungen}}
:[[Taucher]], [[Tauchgang]], [[Tauchstation]], [[Tauchboot]]

== tauchen ({{Sprache|Englisch}}) ==
{{Unterbegriffe}}
:[[foreign]]
"""
        self.assertEqual(
            extract_unterbegriffe(text, "tauchen"),
            ["abtauchen", "antauchen", "auftauchen"],
        )

    def test_combines_sections_even_when_unterbegriffe_is_larger(self):
        text = """{{Unterbegriffe}}
:[[abtauchen]], [[auftauchen]]

{{Wortbildungen}}
:[[Taucher]]
"""
        self.assertEqual(extract_unterbegriffe(text, "tauchen"), ["abtauchen", "auftauchen"])

    def test_deduplicates_within_and_across_sections(self):
        text = """{{Unterbegriffe}}
:[[auftauchen]], [[Taucher]]

{{Wortbildungen}}
:[[Taucher]], [[taucher]], [[auftauchen]]
"""
        self.assertEqual(extract_unterbegriffe(text, "tauchen"), ["auftauchen"])

    def test_filters_before_case_insensitive_deduplication(self):
        text = "{{Unterbegriffe}}\n:[[Auftauchen]], [[auftauchen]], [[tauchender]], [[auftauchen lassen]]"
        self.assertEqual(extract_unterbegriffe(text, "tauchen"), ["auftauchen"])

    def test_handles_a_single_section_or_no_sections(self):
        for name in ("Unterbegriffe", "Wortbildungen"):
            with self.subTest(section=name):
                self.assertEqual(
                    extract_unterbegriffe("{{" + name + "}}\n:[[auftauchen]]\n", "tauchen"),
                    ["auftauchen"],
                )
        self.assertEqual(extract_unterbegriffe("{{Beispiele}}\n:[[tauchen]]", "tauchen"), [])


class FrequencyVerbTests(unittest.TestCase):
    def test_uses_tagged_verbs_from_either_source_and_keeps_missing_frequency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dereko = root / "dereko"
            dereko.write_text("verfehlen\tverfehlen\tVVINF\t12\nFehler\tFehler\tNN\t2\nxfehlen\txfehlen\tVVINF\t4\n", encoding="utf-8")
            joined = root / "joined"
            joined.write_text("word|dwds_freq|dereko_freq|german_api_pos\nabfehlen|20||verb\nFehlfehlen|10||noun\nqfehlen|3||verb\n", encoding="utf-8")
            self.assertEqual(frequency_verbs("fehlen", str(joined), dereko), ["abfehlen", "verfehlen"])
            rows = list(build_rows("fehlen", ["verfehlen"], {}, {}, {}, False))
            self.assertEqual([row["word"] for row in rows], ["fehlen", "verfehlen"])
            self.assertEqual(rows[1]["word_freq"], "")

    @patch("scripts.wiktionary_unterbegriffe.frequency_verbs", return_value=[])
    @patch("scripts.wiktionary_unterbegriffe.fetch_wiktionary_wikitext", return_value="{{Unterbegriffe}}\n:[[pflegen]]")
    def test_empty_family_removes_stale_output(self, _fetch, _frequency):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "legen.csv"
            output.write_text("stale", encoding="utf-8")
            self.assertEqual(main(["legen", "--output", str(output)]), 0)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
