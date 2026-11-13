import dataclasses
import itertools
from typing import List

import pytest

from sqlfmt.analyzer import Analyzer
from sqlfmt.exception import SqlfmtParsingError
from sqlfmt.node_manager import NodeManager
from sqlfmt.rule import Rule
from sqlfmt.rules import CLONE, FUNCTION, GRANT, JINJA, MAIN, UNSUPPORTED, WAREHOUSE

CHARS = [chr(i) for i in range(128)] + ["K", "ſ", "\xa0"]
SUFFIXES = ["", "a", "1", " ", "\n", "'a'", "(a)", "{{ x }}", "% if x %}", "*/"]
SOURCES = [
    prefix + char + suffix
    for prefix, char, suffix in itertools.product(["", " ", "\t "], CHARS, SUFFIXES)
]


@pytest.mark.parametrize(
    "ruleset", [CLONE, FUNCTION, GRANT, JINJA, MAIN, UNSUPPORTED, WAREHOUSE]
)
def test_lex_one_picks_first_matching_rule(ruleset: List[Rule]) -> None:
    """
    lex_one only tries the rules that can match the next char; it must still
    pick the same rule as trying every rule in priority order
    """
    fired: List[str] = []
    rules = [
        dataclasses.replace(rule, action=lambda *_, name=rule.name: fired.append(name))
        for rule in sorted(ruleset, key=lambda rule: rule.priority)
    ]
    analyzer = Analyzer(line_length=88, rules=rules, node_manager=NodeManager(False))
    mismatches = []
    for source in SOURCES:
        expected = [rule.name for rule in rules if rule.program.match(source)][:1]
        fired.clear()
        analyzer.pos = 0
        try:
            analyzer.lex_one(source)
        except SqlfmtParsingError:
            pass
        if fired != expected:
            mismatches.append((source, fired.copy(), expected))
    assert mismatches == []
