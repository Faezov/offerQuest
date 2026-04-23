from __future__ import annotations

import unittest

from offerquest.matching import (
    contains_any_keyword,
    contains_keyword,
    contains_token_sequence,
    find_pattern_matches,
    prepare_matchable_text,
    tokenize_text,
)


class PrepareMatchableTextTests(unittest.TestCase):
    def test_tokenizes_lowercase(self) -> None:
        result = prepare_matchable_text("Hello World")
        self.assertEqual(result.tokens, ("hello", "world"))

    def test_strips_punctuation(self) -> None:
        result = prepare_matchable_text("Python, SQL & R.")
        self.assertIn("python", result.token_set)
        self.assertIn("sql", result.token_set)
        self.assertIn("r", result.token_set)

    def test_token_set_contains_all_tokens(self) -> None:
        result = prepare_matchable_text("data engineer")
        self.assertEqual(result.token_set, frozenset({"data", "engineer"}))

    def test_normalized_joins_tokens(self) -> None:
        result = prepare_matchable_text("Senior Data Analyst")
        self.assertEqual(result.normalized, "senior data analyst")

    def test_empty_string(self) -> None:
        result = prepare_matchable_text("")
        self.assertEqual(result.tokens, ())
        self.assertEqual(result.token_set, frozenset())

    def test_returns_same_object_for_same_input(self) -> None:
        a = prepare_matchable_text("machine learning")
        b = prepare_matchable_text("machine learning")
        self.assertIs(a, b)


class TokenizeTextTests(unittest.TestCase):
    def test_basic(self) -> None:
        self.assertEqual(tokenize_text("SQL, Python"), ["sql", "python"])

    def test_numbers(self) -> None:
        self.assertIn("5", tokenize_text("5 years experience"))


class ContainsKeywordTests(unittest.TestCase):
    def test_single_word_match(self) -> None:
        self.assertTrue(contains_keyword("Python developer", "python"))

    def test_single_word_no_match(self) -> None:
        self.assertFalse(contains_keyword("Java developer", "python"))

    def test_multi_word_match(self) -> None:
        self.assertTrue(contains_keyword("machine learning engineer", "machine learning"))

    def test_multi_word_no_match_partial(self) -> None:
        self.assertFalse(contains_keyword("machine translation expert", "machine learning"))

    def test_accepts_matchable_text(self) -> None:
        prepared = prepare_matchable_text("data analyst")
        self.assertTrue(contains_keyword(prepared, "data analyst"))

    def test_empty_keyword(self) -> None:
        self.assertFalse(contains_keyword("anything", ""))


class ContainsAnyKeywordTests(unittest.TestCase):
    def test_matches_first(self) -> None:
        self.assertTrue(contains_any_keyword("SQL expert", ["sql", "python"]))

    def test_matches_second(self) -> None:
        self.assertTrue(contains_any_keyword("Python developer", ["sql", "python"]))

    def test_no_match(self) -> None:
        self.assertFalse(contains_any_keyword("Java developer", ["sql", "python"]))

    def test_empty_list(self) -> None:
        self.assertFalse(contains_any_keyword("anything", []))


class ContainsTokenSequenceTests(unittest.TestCase):
    def test_match_at_start(self) -> None:
        self.assertTrue(contains_token_sequence(("machine", "learning", "ops"), ("machine", "learning")))

    def test_match_at_end(self) -> None:
        self.assertTrue(contains_token_sequence(("senior", "data", "analyst"), ("data", "analyst")))

    def test_no_match(self) -> None:
        self.assertFalse(contains_token_sequence(("data", "engineer"), ("data", "analyst")))

    def test_needle_longer_than_haystack(self) -> None:
        self.assertFalse(contains_token_sequence(("data",), ("data", "analyst")))

    def test_exact_match(self) -> None:
        self.assertTrue(contains_token_sequence(("sql",), ("sql",)))


class FindPatternMatchesTests(unittest.TestCase):
    def test_returns_matching_labels(self) -> None:
        patterns = {
            "SQL": ["sql", "postgres"],
            "Python": ["python"],
            "Java": ["java", "spring"],
        }
        result = find_pattern_matches("SQL and Python developer", patterns)
        self.assertIn("SQL", result)
        self.assertIn("Python", result)
        self.assertNotIn("Java", result)

    def test_returns_sorted(self) -> None:
        patterns = {"Z skill": ["z"], "A skill": ["a"]}
        result = find_pattern_matches("a z text", patterns)
        self.assertEqual(result, ["A skill", "Z skill"])

    def test_no_matches(self) -> None:
        result = find_pattern_matches("nothing relevant", {"SQL": ["sql"]})
        self.assertEqual(result, [])

    def test_accepts_matchable_text(self) -> None:
        prepared = prepare_matchable_text("Python developer")
        result = find_pattern_matches(prepared, {"Python": ["python"]})
        self.assertEqual(result, ["Python"])
