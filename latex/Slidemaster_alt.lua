-- SPDX-FileCopyrightText: 2026 Stefan Palan, Jürgen Fleiß
-- SPDX-License-Identifier: LPPL-1.3c+
-- Lua side of the alt-text manifest (ALT_TEXT_NOTES.md, phase 1).
--
-- Loaded from Slidemaster_preamble_base.tex's "Alt-text manifest" block.
-- This lives in its own .lua file rather than inline in a \directlua{...}
-- argument for one blunt reason: TeX tokenizes that argument *before* Lua
-- ever sees it, so "%" starts a TeX comment and silently truncates the line.
-- Lua string patterns are full of "%" ("%.[^.]*$" to strip an extension),
-- and "#" for table length needs escaping too -- inline, all of that has to
-- be written as \string# and catcode-juggled percents, and one missed escape
-- kills the whole chunk with a syntax error at some unrelated later line.
-- (That is not hypothetical: the first version of this was inline and failed
-- exactly that way, with "attempt to index a nil value (global 'gothamalt')"
-- at every \includegraphics because the chunk defining the table never
-- parsed.) In a .lua file none of those characters are special.

gothamalt = { by_name = {}, by_stem = {} }

-- Each entry is { role = "...", short_en = "...", short_de = "...",
-- source_en = "...", source_de = "..." } (widened 2026-08-24 for
-- multi-language -- see LANGUAGE_NOTES.md; role stays a single shared
-- field, since decorative/informative is a property of the picture, not
-- of which language is being read). The short alt is what the
-- invisible-text layer (phase 5) emits next to an informative image; the
-- role is what phase 1 uses to mark a decorative one as an /Artifact;
-- source (added phase 6 step 3) feeds the per-frame "Image source(s):"/
-- "Bildquelle(n):" auto-footnote further below. Which language's pair
-- (_en/_de) actually gets used is decided per-call by gothamalt.altText/
-- recordSource's own `language` argument (the compiling deck's
-- \SMDeckLanguage), not by anything stored here.

-- Minimal RFC-4180-ish field splitter: handles quoted fields with embedded
-- commas and doubled quotes, because every short_alt/source column can
-- contain both once the SlideMage review tab writes them. A trailing
-- empty field is not reported, which is fine -- only columns 1 (image),
-- 2 (role), 4/5 (short_alt_en/source_en) and 7/8 (short_alt_de/source_de)
-- are ever read here (3 and 6, status_en/status_de, are for SlideMage's
-- own UI, not compile-time gating -- see alt_images.py's own docstring).
local function parse_line(line)
	local fields, pos, len = {}, 1, #line
	repeat
		if line:sub(pos, pos) == '"' then
			local buf = {}
			pos = pos + 1
			while pos <= len do
				local c = line:sub(pos, pos)
				if c == '"' then
					if line:sub(pos + 1, pos + 1) == '"' then
						buf[#buf + 1] = '"'
						pos = pos + 2
					else
						pos = pos + 1
						break
					end
				else
					buf[#buf + 1] = c
					pos = pos + 1
				end
			end
			fields[#fields + 1] = table.concat(buf)
			local comma = line:find(",", pos, true)
			if not comma then break end
			pos = comma + 1
		else
			local comma = line:find(",", pos, true)
			if not comma then
				fields[#fields + 1] = line:sub(pos)
				break
			end
			fields[#fields + 1] = line:sub(pos, comma - 1)
			pos = comma + 1
		end
	until pos > len
	return fields
end

-- Candidate paths, because a deck compiles either from the project root or
-- from inside decks/ (see README.md on \input@path/\graphicspath), and Lua's
-- io.open resolves against the process working directory -- which latexmk's
-- $do_cd makes the compiled file's own directory. kpathsea's fallback search
-- does not cover a .csv, so the two locations are tried explicitly.
local CSV_CANDIDATES = { "media/alt-text.csv", "../media/alt-text.csv" }

function gothamalt.load()
	for _, path in ipairs(CSV_CANDIDATES) do
		local handle = io.open(path, "r")
		if handle then
			local header = true
			for line in handle:lines() do
				line = line:gsub("\r$", "")
				if header then
					header = false
				elseif line ~= "" then
					local fields = parse_line(line)
					local image, role = fields[1], fields[2]
					local short_en = fields[4] or ""
					local source_en = fields[5] or ""
					local short_de = fields[7] or ""
					local source_de = fields[8] or ""
					if image and role and image ~= "" then
						local name = image:match("([^/\\]+)$") or image
						name = name:lower()
						local stem = name:match("^(.*)%.[^.]*$") or name
						local entry = {
							role = role,
							short_en = short_en, short_de = short_de,
							source_en = source_en, source_de = source_de,
						}
						gothamalt.by_name[name] = entry
						if gothamalt.by_stem[stem] == nil then
							gothamalt.by_stem[stem] = entry
						end
					end
				end
			end
			handle:close()
			return path
		end
	end
	return nil
end

-- Matching is on the basename (lowercased -- this is a Windows project and
-- the filesystem is case-insensitive), falling back to the extensionless
-- stem, so "media/foo.png", "../media/foo.png" and a bare "media/foo"
-- (graphicx picking the suffix itself, as the institution preambles do) all
-- resolve to the same row.
function gothamalt.lookup(reference)
	reference = reference:gsub("\\", "/")
	local name = (reference:match("([^/]+)$") or reference):lower()
	local entry = gothamalt.by_name[name]
	if entry then
		return entry
	end
	local stem = name:match("^(.*)%.[^.]*$") or name
	return gothamalt.by_stem[stem]
end

function gothamalt.role(reference)
	local entry = gothamalt.lookup(reference)
	return entry and entry.role or ""
end

-- TeX specials, escaped rather than stripped, so the alt text a screen
-- reader speaks is exactly the text the author reviewed. Backslash first:
-- escaping it afterwards would also escape the backslashes just inserted.
function gothamalt.escape(text)
	text = text:gsub("\\", "\\textbackslash ")
	text = text:gsub("([%%%$&#_{}])", "\\%1")
	text = text:gsub("%^", "\\textasciicircum ")
	text = text:gsub("~", "\\textasciitilde ")
	return text
end

-- Emit the short alt for an *informative* image, or nothing at all.
-- Decorative images are silenced by the /Artifact marking instead, and an
-- image with no short alt yet contributes nothing -- so this degrades to
-- today's behaviour until the manifest is filled in.
-- Sets a TeX conditional and stashes the text in a macro, rather than simply
-- printing it. The caller has to know whether there *is* any alt text before
-- it opens the invisible-text box: otherwise an image with no description yet
-- still emits the "Image: " prefix, and a screen reader announces an image
-- and then says nothing about it -- worse than staying silent.
--
-- `language` ("en"/"de", the compiling deck's own \SMDeckLanguage,
-- passed through by the \includegraphics wrapper) picks which pair to
-- read (2026-08-24). Unlike source below, short_alt has no default+
-- override fallback: an untranslated German short_alt just means no
-- invisible alt text for that image under a German compile, same as an
-- empty English one does today -- real "is this deck's alt text
-- complete" gating belongs in the SlideMage review UI, not here.
function gothamalt.altText(reference, language)
	local entry = gothamalt.lookup(reference)
	if entry == nil or entry.role == "decorative" then
		return
	end
	local raw = (language == "de") and entry.short_de or entry.short_en
	local short = (raw or ""):gsub("^%s+", ""):gsub("%s+$", "")
	if short == "" then
		return
	end
	tex.sprint("\\SMAltHasTexttrue\\def\\SMAltShort{"
		.. gothamalt.escape(short) .. "}")
end

-- Called once per \includegraphics. Sets the TeX-side conditional rather
-- than returning a string, so the caller never has to string-compare in TeX.
function gothamalt.mark(reference)
	if gothamalt.role(reference) == "decorative" then
		tex.sprint("\\SMAltDecorativetrue")
	end
end

-- ---------------------------------------------------------------------------
-- Per-frame "Image source(s):" auto-footnote (ALT_TEXT_NOTES.md phase 6
-- step 3)
-- ---------------------------------------------------------------------------
-- Unlike short/alt above, source applies regardless of role -- a decorative
-- Midjourney illustration still needs attribution -- so recordSource() is
-- called unconditionally from the \includegraphics wrapper, for every image,
-- not just informative ones.
--
-- frame_sources is an ordered list (first-appearance order, matching
-- reading/content-stream order the same way the alt-text layer already
-- does) and frame_sources_seen is a parallel set, so the same image used
-- twice in one frame (or two different images that happen to share
-- identical source text, e.g. two panels of one figure) contributes its
-- source only once. Reset once per \begin{standardframe} pass -- beamer
-- replays a frame's whole body once per overlay step, and standardframe's
-- own opening code already resets its side-footnote box the same way on
-- every one of those replays (see \SMClearSideFootnotesBox), so this
-- follows the identical pattern: every overlay step of a multi-step frame
-- sees the frame's full, identical set of images (only their *visibility*
-- is gated per step, not whether the \includegraphics call itself runs),
-- so the emitted footnote is the same on every step too -- consistent with
-- how a hand-authored \source{} written outside any overlay conditional
-- already behaves.
gothamalt.frame_sources = {}
gothamalt.frame_sources_seen = {}

function gothamalt.resetFrameSources()
	gothamalt.frame_sources = {}
	gothamalt.frame_sources_seen = {}
end

-- `language` picks source_en/source_de the same way altText() above picks
-- short_en/short_de -- except source_de *does* fall back to source_en
-- when empty (2026-08-24, mirrors alt_images.ImageEntry.source_for_de()
-- on the Python side exactly): most citations are proper nouns/
-- publication names ("KAL, 1989, Baltimore Sun") that don't need
-- translating, so a translator only has to fill in source_de for the
-- genuine exceptions rather than copy every citation by hand.
function gothamalt.recordSource(reference, language)
	local entry = gothamalt.lookup(reference)
	if entry == nil then
		return
	end
	local source
	if language == "de" then
		source = entry.source_de
		if source == nil or source == "" then
			source = entry.source_en
		end
	else
		source = entry.source_en
	end
	source = (source or ""):gsub("^%s+", ""):gsub("%s+$", "")
	if source == "" then
		return
	end
	if not gothamalt.frame_sources_seen[source] then
		gothamalt.frame_sources_seen[source] = true
		gothamalt.frame_sources[#gothamalt.frame_sources + 1] = source
	end
end

-- Strips trailing period(s) (plus any trailing whitespace) from one source
-- entry before joining -- most stored citations already end in "." (e.g.
-- "Source: Datastream."), some don't (a bare \fullcite{key} call), and
-- joining raw would produce a stray ".." wherever a period-ending entry
-- isn't last. Normalizing every entry to no trailing period, then joining
-- with ". " and adding exactly one final period, gives a clean result
-- regardless of how any individual entry was originally punctuated.
local function strip_trailing_period(text)
	return (text:gsub("%.+%s*$", ""))
end

-- Sets a TeX-side conditional plus a stashed macro, same pattern as
-- gothamalt.altText above, rather than tex.sprint-ing a \source{...} call
-- directly -- keeps "whether/how to call \source{}" a TeX-side decision
-- (SMEmitImageSourceFootnote below) rather than baked into this string.
-- Deliberately NOT run through gothamalt.escape(): unlike the invisible
-- alt-text layer (which types literal PDF-string glyphs via a raw
-- \pdfextension primitive and therefore needs every TeX special character
-- escaped to appear as its own glyph), this text is fed back into the real
-- TeX token stream and expanded as ordinary LaTeX -- \href{}/\fullcite{}
-- calls inside a stored source value need to actually execute as macros,
-- exactly as they would if hand-typed inside a \source{...} call, which is
-- literally where this text was extracted from.
function gothamalt.emitSourceFootnote()
	if #gothamalt.frame_sources == 0 then
		return
	end
	local parts = {}
	for i, source in ipairs(gothamalt.frame_sources) do
		parts[i] = strip_trailing_period(source)
	end
	local joined = table.concat(parts, ". ") .. "."
	tex.sprint("\\SMImageSourcesHasTexttrue\\def\\SMImageSourcesText{"
		.. joined .. "}")
end
