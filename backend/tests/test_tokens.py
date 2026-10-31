"""Tokenisation must keep every script: an ASCII-only normaliser once made Tamil and Gujarati narrations share a token."""
import os
import sys
import tempfile

os.environ["FINSIGHT_DATA_DIR"] = tempfile.mkdtemp(prefix="finsight_tok_")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.security.crypto import token  # noqa: E402

assert token("பணம் செலுத்துதல்/BR சென்னை", "d") != token("રોકડ જમા/BR અમદાવાદ", "d"), "narrations in different scripts collided"
assert token("नकद आहरण/ATM", "d") != token("नकद जमा/ATM", "d"), "Devanagari narrations collided"
assert token("हेतल शाह", "name") != token("રમેશ પટેલ", "name"), "names in different scripts collided"
assert token("किराया", "name") != token("करय", "name"), "vowel signs were dropped"
assert token("Hetal  Shah", "name") == token("HETAL SHAH", "name"), "name matching should ignore case and spacing"
assert token("5010-0234", "acct") == token("50100234", "acct"), "account matching should ignore separators"
print("ALL TOKEN CHECKS PASSED")
