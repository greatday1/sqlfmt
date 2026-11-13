import re
from dataclasses import dataclass
from functools import cached_property
from re import _parser  # type: ignore[attr-defined]
from typing import TYPE_CHECKING, Any, Callable, FrozenSet, Optional, Set, Tuple

if TYPE_CHECKING:
    from sqlfmt.analyzer import Analyzer

MAYBE_WHITESPACES: str = r"[^\S\n]*"  # any whitespace except newline


@dataclass
class Rule:
    """
    A lex rule.

    When the analyzer lexes the source string, it applies each Rule in turn,
    in ascending order of priority.

    The Analyzer tries to match the Rule's regex pattern to the current position
    in the source string. If there is a match, the Analyzer calls the Rule's
    action with the arguments (self [the analyzer], source_string, match). The
    Rule's action may mutate the analyzer's buffer (if desired). The action
    must return the position in the source_string where the Analyzer should
    look for the next match.
    """

    name: str
    priority: int  # lower get matched first
    pattern: str
    action: Callable[["Analyzer", str, re.Match], None]

    def __post_init__(self) -> None:
        self.program = re.compile(
            MAYBE_WHITESPACES + self.pattern, re.IGNORECASE | re.DOTALL
        )

    @cached_property
    def first(self) -> Optional[FrozenSet[str]]:
        """
        The ASCII characters this rule can match at the first character after
        MAYBE_WHITESPACES, or None if it could match anywhere (it can match
        empty, start with whitespace, or its pattern is too hard to analyze).
        A superset is always safe, so anything unrecognized gives up with None.
        """
        chars, nullable = _first(_parser.parse(self.pattern, self.program.flags))
        if chars is None or nullable or chars & _HSPACE:
            return None
        return frozenset(chars)


_ASCII = [chr(i) for i in range(128)]
_HSPACE = frozenset(c for c in _ASCII if c.isspace() and c != "\n")
_CATEGORIES = {
    _parser.CATEGORY_DIGIT: frozenset("0123456789"),
    _parser.CATEGORY_SPACE: frozenset(c for c in _ASCII if c.isspace()),
    _parser.CATEGORY_WORD: frozenset(c for c in _ASCII if c.isalnum() or c == "_"),
}


def _first(seq: Any) -> Tuple[Optional[Set[str]], bool]:
    """
    Returns (the ASCII chars a non-empty match of the parsed regex seq can start
    with, or None for any char; whether seq can match the empty string)
    """
    first: Set[str] = set()
    for i, (op, av) in enumerate(seq):
        chars: Optional[Set[str]]
        if op is _parser.LITERAL:
            chars, nullable = (_cased(chr(av)) if av < 128 else None), False
        elif op is _parser.IN:
            chars, nullable = _charset(av), False
        elif op is _parser.BRANCH:
            chars, nullable = set(), False
            for branch in av[1]:
                bchars, bnullable = _first(branch)
                if bchars is None:
                    return None, False
                chars |= bchars
                nullable |= bnullable
        elif op is _parser.SUBPATTERN:
            chars, nullable = _first(av[-1])
        elif op is _parser.ATOMIC_GROUP:
            chars, nullable = _first(av)
        elif op in (_parser.MAX_REPEAT, _parser.MIN_REPEAT, _parser.POSSESSIVE_REPEAT):
            chars, nullable = _first(av[2])
            nullable |= av[0] == 0
        elif op is _parser.ASSERT and av[0] == 1:
            # a lookahead constrains the next char no matter what follows it
            ahead, ahead_nullable = _first(av[1])
            if ahead is None or ahead_nullable:
                continue
            rest, nullable = _first(seq[i + 1 :])
            return first | (ahead if rest is None else rest & ahead), nullable
        elif op in (_parser.AT, _parser.ASSERT, _parser.ASSERT_NOT):
            continue  # zero-width; ignoring it is a superset
        else:
            return None, False
        if chars is None:
            return None, False
        first |= chars
        if not nullable:
            return first, False
    return first, True


def _charset(items: Any) -> Optional[Set[str]]:
    chars: Set[str] = set()
    for op, av in items:
        if op is _parser.LITERAL and av < 128:
            chars.add(chr(av))
        elif op is _parser.RANGE and av[1] < 128:
            chars.update(map(chr, range(av[0], av[1] + 1)))
        elif op is _parser.CATEGORY and av in _CATEGORIES:
            chars |= _CATEGORIES[av]
        else:  # NEGATE, non-ASCII, unknown categories
            return None
    return {c for ch in chars for c in _cased(ch)}


def _cased(ch: str) -> Set[str]:
    # every rule is IGNORECASE. Fold at the leaves so lookahead intersections
    # compare like with like. Non-ASCII chars that fold to ASCII (e.g. KELVIN
    # SIGN) never get here: _first gives up on them, and the analyzer sends
    # non-ASCII source chars to every rule.
    return {ch.lower(), ch.upper()}
