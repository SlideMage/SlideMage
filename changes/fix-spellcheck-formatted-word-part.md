kind: fixed
reason: direct request: the spell checker flagged "ypothesizing" in \underline{h}ypothesizing, and "oldid" in a URL typed with \_ and \&

A word that is formatted in part (\underline{h}ypothesizing, un\textbf{like}ly) was cut at the braces and its pieces were checked on their own. Such a word is now left out whole, as words with an accent or a hyphenation hint inside already were. Footnotes and other text after a word are not affected. An address written with LaTeX escapes (Data\_dredging\&oldid=1) was cut at the first backslash and its tail checked as words; the escapes \_ \& \% \# \~ now belong to the address.

NEW: The spell checker no longer flags parts of formatted words or of addresses typed with escaped characters.
- A word that is formatted in part is skipped instead of being reported as misspelled.
- A link text such as https://en.wikipedia.org/w/index.php?title=Data\_dredging\&oldid=1 is skipped whole.
