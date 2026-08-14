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

-- Each entry is { role = "...", short = "..." }. The short alt is what the
-- invisible-text layer (phase 5) emits next to an informative image; the role
-- is what phase 1 uses to mark a decorative one as an /Artifact.

-- Minimal RFC-4180-ish field splitter: handles quoted fields with embedded
-- commas and doubled quotes, because short_alt (column 4) will contain both
-- once the SlideManager review tab starts writing it. A trailing empty field
-- is not reported, which is fine -- only columns 1 (image) and 2 (role) are
-- ever read here.
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
					local short = fields[4] or ""
					if image and role and image ~= "" then
						local name = image:match("([^/\\]+)$") or image
						name = name:lower()
						local stem = name:match("^(.*)%.[^.]*$") or name
						local entry = { role = role, short = short }
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
function gothamalt.altText(reference)
	local entry = gothamalt.lookup(reference)
	if entry == nil or entry.role == "decorative" then
		return
	end
	local short = (entry.short or ""):gsub("^%s+", ""):gsub("%s+$", "")
	if short == "" then
		return
	end
	tex.sprint("\\gothamAltHasTexttrue\\def\\gothamAltShort{"
		.. gothamalt.escape(short) .. "}")
end

-- Called once per \includegraphics. Sets the TeX-side conditional rather
-- than returning a string, so the caller never has to string-compare in TeX.
function gothamalt.mark(reference)
	if gothamalt.role(reference) == "decorative" then
		tex.sprint("\\gothamAltDecorativetrue")
	end
end
