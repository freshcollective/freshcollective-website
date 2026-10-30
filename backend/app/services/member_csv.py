"""Reading a member list out of somebody else's export.

A creator moving a community to Fresh Collective arrives with a CSV
from wherever they were before, and those files disagree about almost
everything: the column is ``Email`` or ``E-mail`` or ``Email Address``;
the name is one column or two; there is a byte-order mark on the front
because it came out of Excel. None of that is the creator's problem to
fix in a text editor.

So this module only reads. It decides nothing about membership and
writes nothing — the caller matches the rows against the Collective and
creates invitations through the ordinary invitation path. Keeping the
parse separate is what lets the preview and the import agree: both ask
this module the same question and get the same answer.

Nothing here logs a row. An imported file is somebody's contact list,
and a parser that printed a malformed line would put an email address
into the logs of a feature whose whole job is to handle them carefully.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

#: An address shaped like an address. Deliberately not RFC 5322 — that
#: grammar accepts things no mail server will, and the only useful
#: question here is whether a human typed something plausible into a
#: spreadsheet. The invitation itself is the real test.
_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;.]+(\.[^@\s,;.]+)+$")

#: Headings seen in exports from other community platforms, lowercased
#: and stripped of punctuation. Order matters only in that the first
#: match wins.
_EMAIL_HEADINGS = (
    "email", "email address", "e mail", "e mail address",
    "member email", "user email", "contact email", "primary email",
    "email 1", "work email",
)
_NAME_HEADINGS = (
    "name", "full name", "display name", "member name", "member",
    "contact name", "username",
)
_FIRST_NAME_HEADINGS = ("first name", "firstname", "given name", "first")
_LAST_NAME_HEADINGS = ("last name", "lastname", "surname", "family name", "last")

#: Ceilings. A CSV is read entirely into memory and every row becomes a
#: question asked of the database, so both are bounded. Generous enough
#: for the community sizes this feature exists for, small enough that a
#: mistaken upload cannot become an outage.
MAX_CSV_BYTES = 2 * 1024 * 1024      # 2 MB
MAX_CSV_ROWS = 2000


class CsvFormatError(ValueError):
    """The file could not be read as a member list.

    Carries a message meant for the creator, not a stack trace — and
    never any part of the file's contents.
    """


class MissingEmailColumn(CsvFormatError):
    """The file is readable, but which column holds the addresses?

    A separate type because this is the one failure a creator can fix
    without leaving the screen, and fixing it needs the headings. The
    preview answers with them and a column picker rather than an error.
    """

    def __init__(self, message: str, headings: list[str]) -> None:
        super().__init__(message)
        self.headings = headings


@dataclass
class ParsedRow:
    #: 1-based, counting the header, so it matches what a spreadsheet
    #: shows the creator when they go looking.
    line: int
    email: str
    name: str | None


@dataclass
class ParsedCsv:
    headings: list[str] = field(default_factory=list)
    email_column: str | None = None
    name_column: str | None = None
    rows: list[ParsedRow] = field(default_factory=list)
    #: Line numbers whose email could not be read. Numbers only — the
    #: creator is told how many and where, never shown the value back.
    invalid_lines: list[int] = field(default_factory=list)
    #: Lines dropped because an earlier line held the same address.
    duplicate_lines: list[int] = field(default_factory=list)
    truncated: bool = False


def _normalise(heading: str) -> str:
    """``" E-Mail_Address "`` → ``"e mail address"``."""
    return re.sub(r"[^a-z0-9]+", " ", heading.strip().lower()).strip()


def _find(
    headings: list[str],
    candidates: tuple[str, ...],
    *,
    exclude: tuple[str | None, ...] = (),
    substring: bool = True,
) -> str | None:
    norm = {
        _normalise(h): h for h in headings if h not in exclude
    }
    for c in candidates:
        if c in norm:
            return norm[c]
    if not substring:
        return None
    # Nothing exact — accept a heading that merely contains the word,
    # which catches "Primary Email (verified)" and its relatives.
    for n, original in norm.items():
        if any(c in n for c in candidates):
            return original
    return None


def _find_split_name(headings: list[str]) -> tuple[str | None, str | None]:
    """Locate separate first- and last-name columns.

    Exact matches only. "last" loosely matched would claim "Last seen"
    or "Last active", which plenty of exports carry, and a name built
    from one of those would be a date glued to a first name.
    """
    return (
        _find(headings, _FIRST_NAME_HEADINGS, substring=False),
        _find(headings, _LAST_NAME_HEADINGS, substring=False),
    )


def sniff_columns(headings: list[str]) -> tuple[str | None, str | None]:
    """Guess which column holds the email, and which the name.

    A split first/last pair wins over a loose match on the word "name",
    which would otherwise claim "First Name" for the whole name and
    quietly drop the surname.
    """
    email = _find(headings, _EMAIL_HEADINGS)
    first, last = _find_split_name(headings)
    name = _find(headings, _NAME_HEADINGS, exclude=(first, last))
    return email, name


def parse_member_csv(
    data: bytes,
    *,
    email_column: str | None = None,
    name_column: str | None = None,
) -> ParsedCsv:
    """Read a member list.

    ``email_column`` and ``name_column`` override the guess, which is
    how a file with unrecognisable headings is imported without being
    edited first.
    """
    if len(data) > MAX_CSV_BYTES:
        raise CsvFormatError(
            f"That file is larger than {MAX_CSV_BYTES // (1024 * 1024)} MB. "
            "Try splitting it into smaller files."
        )
    if not data.strip():
        raise CsvFormatError("That file is empty.")

    # ``utf-8-sig`` eats the byte-order mark Excel writes; latin-1 is the
    # fallback that cannot fail, so a file in an unknown encoding is
    # imported with the odd mangled character rather than refused.
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1", errors="replace")

    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)

    headings = [h for h in (reader.fieldnames or []) if h is not None]
    if not headings:
        raise CsvFormatError("That file has no column headings.")

    guessed_email, guessed_name = sniff_columns(headings)
    email_col = email_column or guessed_email
    name_col = name_column or guessed_name

    if email_col is None:
        raise MissingEmailColumn(
            "We couldn't find an email column. Choose which column holds "
            "the email addresses, or add a column headed “Email”.",
            headings,
        )
    if email_col not in headings:
        raise CsvFormatError("That column isn't in the file.")
    if name_col is not None and name_col not in headings:
        name_col = None

    first_col, last_col = _find_split_name(headings)

    out = ParsedCsv(headings=headings, email_column=email_col, name_column=name_col)
    seen: set[str] = set()

    for index, raw in enumerate(reader):
        line = index + 2          # +1 for zero-based, +1 for the header
        if len(out.rows) >= MAX_CSV_ROWS:
            out.truncated = True
            break

        email = (raw.get(email_col) or "").strip().lower()
        if not email:
            # A wholly blank line is the trailing newline every
            # spreadsheet writes, not a mistake worth reporting.
            if not any((v or "").strip() for v in raw.values()):
                continue
            out.invalid_lines.append(line)
            continue
        if not _EMAIL_RE.match(email):
            out.invalid_lines.append(line)
            continue
        if email in seen:
            out.duplicate_lines.append(line)
            continue
        seen.add(email)

        name: str | None = None
        if name_col:
            name = (raw.get(name_col) or "").strip() or None
        if not name and (first_col or last_col):
            parts = [
                (raw.get(c) or "").strip()
                for c in (first_col, last_col) if c
            ]
            name = " ".join(p for p in parts if p) or None

        out.rows.append(ParsedRow(line=line, email=email, name=name[:200] if name else None))

    return out


#: The file offered as a starting point. Two columns, because that is
#: all the invitation needs.
SAMPLE_CSV = (
    "Name,Email\r\n"
    "Ada Lovelace,ada@example.com\r\n"
    "Grace Hopper,grace@example.com\r\n"
)
