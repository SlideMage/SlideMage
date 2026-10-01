-- Slidemaster_layout.lua -- Lua half of the layout helpers in
-- Slidemaster_preamble_base.tex. In its own file, not inline in \directlua,
-- for the same reason as Slidemaster_alt.lua: TeX tokenizes a \directlua
-- argument first, so a "%" in a Lua string pattern would silently comment
-- out the rest of its line.

gotham_layout = gotham_layout or {}

---------------------------------------------------------------------------
-- gothamtable[gap=<length>]: turn a plain column spec into the
-- flush-edge form every gothamtable used to be written in by hand,
--   @{} col1 <{\hspace{gap}} col2 <{\hspace{gap}} ... colN @{}
-- (with \tabcolsep set to 0pt by the environment). The gap goes *inside*
-- the preceding column (a <{} suffix), so \rowcolor tints it like the rest
-- of the row, and the rules end exactly at the outermost text.
--
-- After a fixed-width column (p/m/b/w/W) the gap is an @{\hspace{gap}}
-- separator instead: array puts a <{} suffix *inside* such a column's box,
-- where it would pad the cell text rather than separate the columns.
--
-- A column is: any number of >{...} prefixes, a column letter with its
-- arguments (p/m/b take one {...}, w/W take two, others none; an optional
-- [...] is kept, e.g. siunitx S[...]), any number of <{...} suffixes.
-- @{...} and !{...} between two columns are explicit separators: no gap
-- is added there. | is kept as it is. *{n}{spec} is expanded first.
-- @{} at either end of the given spec is dropped (the environment adds it).
---------------------------------------------------------------------------

local function read_group(s, i)
  -- s:sub(i, i) == "{"; returns the group's content and the index after it
  local depth = 0
  local j = i
  while j <= #s do
    local ch = s:sub(j, j)
    if ch == "\\" then
      j = j + 1
    elseif ch == "{" then
      depth = depth + 1
    elseif ch == "}" then
      depth = depth - 1
      if depth == 0 then
        return s:sub(i + 1, j - 1), j + 1
      end
    end
    j = j + 1
  end
  error("gothamtable: unbalanced braces in column spec: " .. s)
end

local function skip_space(s, i)
  while i <= #s and s:sub(i, i):match("%s") do
    i = i + 1
  end
  return i
end

local function expand_stars(s)
  local out, i = {}, 1
  while i <= #s do
    local ch = s:sub(i, i)
    if ch == "\\" then
      out[#out + 1] = s:sub(i, i + 1)
      i = i + 2
    elseif ch == "*" then
      local j = skip_space(s, i + 1)
      local n, k = read_group(s, j)
      k = skip_space(s, k)
      local body, k2 = read_group(s, k)
      out[#out + 1] = string.rep(expand_stars(body), tonumber(n))
      i = k2
    elseif ch == "{" then
      local body, k = read_group(s, i)
      out[#out + 1] = "{" .. body .. "}"
      i = k
    else
      out[#out + 1] = ch
      i = i + 1
    end
  end
  return table.concat(out)
end

local TWO_ARGS = { w = true, W = true }
local ONE_ARG = { p = true, m = true, b = true }

-- Split a column spec into items: {kind = "col" | "sep", text = ...}
local function split_spec(s)
  local items, i = {}, 1
  local prefix = ""
  while true do
    i = skip_space(s, i)
    if i > #s then
      break
    end
    local ch = s:sub(i, i)
    if ch == ">" then
      local j = skip_space(s, i + 1)
      local body, k = read_group(s, j)
      prefix = prefix .. ">{" .. body .. "}"
      i = k
    elseif ch == "<" then
      local j = skip_space(s, i + 1)
      local body, k = read_group(s, j)
      local last = items[#items]
      if not last or last.kind ~= "col" then
        error("gothamtable: <{...} without a column: " .. s)
      end
      last.text = last.text .. "<{" .. body .. "}"
      i = k
    elseif ch == "@" or ch == "!" then
      local j = skip_space(s, i + 1)
      local body, k = read_group(s, j)
      items[#items + 1] = { kind = "sep", text = ch .. "{" .. body .. "}" }
      i = k
    elseif ch == "|" then
      items[#items + 1] = { kind = "rule", text = "|" }
      i = i + 1
    elseif ch:match("%a") then
      local text = prefix .. ch
      prefix = ""
      local k = i + 1
      local nargs = (TWO_ARGS[ch] and 2) or (ONE_ARG[ch] and 1) or 0
      for _ = 1, nargs do
        k = skip_space(s, k)
        local body, k2 = read_group(s, k)
        text = text .. "{" .. body .. "}"
        k = k2
      end
      local k3 = skip_space(s, k)
      if s:sub(k3, k3) == "[" then
        local close = s:find("]", k3, true)
        text = text .. s:sub(k3, close)
        k = close + 1
      end
      items[#items + 1] = { kind = "col", text = text, fixed = nargs > 0 }
      i = k
    else
      error("gothamtable: unexpected '" .. ch .. "' in column spec: " .. s)
    end
  end
  return items
end

function gotham_layout.gap_spec(spec, gap)
  local items = split_spec(expand_stars(spec))
  -- drop an explicit @{} at either end: the environment adds its own
  if items[1] and items[1].kind == "sep" and items[1].text == "@{}" then
    table.remove(items, 1)
  end
  if items[#items] and items[#items].kind == "sep" and items[#items].text == "@{}" then
    table.remove(items)
  end
  local out = { "@{}" }
  for idx, item in ipairs(items) do
    out[#out + 1] = item.text
    if item.kind == "col" then
      -- a gap unless the next non-rule item is a separator or there is none
      local nxt
      for j = idx + 1, #items do
        if items[j].kind ~= "rule" then
          nxt = items[j]
          break
        end
      end
      if nxt and nxt.kind == "col" then
        if item.fixed then
          -- a p/m/b/w column is a box of fixed width: a <{} suffix would land
          -- inside it (padding the end of the cell text) instead of between
          -- the columns, so the gap goes in as a separator here
          out[#out + 1] = "@{\\hspace{" .. gap .. "}}"
        else
          out[#out + 1] = "<{\\hspace{" .. gap .. "}}"
        end
      end
    end
  end
  out[#out + 1] = "@{}"
  return table.concat(out)
end

-- Called from the gothamtable environment: store the expanded spec in
-- \gothamtable@spec (tokenized with the catcodes in force at the call).
function gotham_layout.set_gap_spec(spec, gap)
  token.set_macro("gothamtable@spec", gotham_layout.gap_spec(spec, gap))
end

---------------------------------------------------------------------------
-- Automatic Top Margin (2026-09-30). Each standardframe writes a marker
-- (a user_defined whatsit) at the start of its body. At shipout the page
-- is walked in document order; the first visible flow content after the
-- marker is measured:
--   a text line   -> baseline - 0.935 x its largest glyph size (Fira Sans'
--                    ascender: the "line box" top every measurement in this
--                    project uses; 41.58bp for a plain first line)
--   an image/rule -> its top edge (a table's \toprule, a picture)
--   a TikZ picture in the flow -> its bounding box top (not looked into:
--                    its content is placed by PDF transforms, not by nodes)
-- Zero-height boxes are skipped: they are the \vbox to 0pt{...} overlays,
-- whose content sits at absolute page positions, not in the flow.
-- The difference to the Top Margin is written to \jobname.top and added to
-- that frame's pull-up on the next run (latexmk reruns while the file
-- changes; moving the body moves the measured line by the same amount, so
-- the second run lands on the margin and the file stays unchanged).
---------------------------------------------------------------------------

local TOP_MARGIN_BP = 41.58
local ASCENDER = 0.935
local MARKER_ID = 20260930
local SP_PER_PT = 65536
local BP_PER_PT = 72 / 72.27

local HLIST, VLIST = node.id("hlist"), node.id("vlist")
local RULE, GLYPH = node.id("rule"), node.id("glyph")
local GLUE, KERN = node.id("glue"), node.id("kern")
local WHATSIT = node.id("whatsit")
local USER_DEFINED = node.subtype("user_defined")
local PDF_SAVE = node.subtype("pdf_save")
local PDF_LITERAL_ST = node.subtype("pdf_literal")
local PDF_SETMATRIX = node.subtype("pdf_setmatrix")
local SMALL_PICTURE = 6 * SP_PER_PT   -- bullet dots, inline icons
local MIN_ROOM_PT = 1                 -- clearance kept above footnotes/footer
local MIN_SIZE = SP_PER_PT // 2

gotham_layout.top_applied = gotham_layout.top_applied or {}
gotham_layout.top_measured = gotham_layout.top_measured or {}
gotham_layout.top_debug = false

-- TeX side: this frame (index) got `applied_pt` of automatic correction
function gotham_layout.top_begin(index, applied_pt)
  gotham_layout.top_applied[index] = applied_pt
  local n = node.new(WHATSIT, USER_DEFINED)
  n.user_id = MARKER_ID
  n.type = 100          -- integer
  n.value = index
  node.write(n)
end

function gotham_layout.top_end(index)
  local n = node.new(WHATSIT, USER_DEFINED)
  n.user_id = MARKER_ID
  n.type = 100
  n.value = -index
  node.write(n)
end

local function is_marker(n)
  return n.id == WHATSIT and n.subtype == USER_DEFINED and n.user_id == MARKER_ID
end

-- a box whose own list holds PDF literals is a picture (TikZ, the bullet
-- dot, ...): its content is placed by PDF transforms, so only the box
-- itself counts. Direct children only -- a text line that merely contains
-- a bullet dot somewhere inside is not a picture.
local function is_picture(box)
  -- a TikZ/pgf picture is always an hbox; a vbox holding a literal (a
  -- minipage with a colour or overlay operator in it) is a text container
  if box.id ~= HLIST then
    return false
  end
  local list = box.head or box.list
  if not list then
    return false
  end
  for n in node.traverse_id(WHATSIT, list) do
    -- pgf's LuaTeX driver draws through \pdfextension save/setmatrix; a bare
    -- literal is not enough (beamer puts some into ordinary rows, e.g. columns)
    if n.subtype == PDF_SAVE or n.subtype == PDF_SETMATRIX then
      return true
    end
  end
  return false
end

-- does the box draw anything through PDF operators, at any depth? (a TikZ
-- picture can sit several boxes deep, e.g. a bordered node around a
-- pgfplots axis)
local function draws(box)
  local list = box.head or box.list
  if not list then
    return false
  end
  for n in node.traverse(list) do
    if n.id == WHATSIT and (n.subtype == PDF_SAVE or n.subtype == PDF_SETMATRIX or n.subtype == PDF_LITERAL_ST) then
      return true
    end
    if (n.id == HLIST or n.id == VLIST) and draws(n) then
      return true
    end
  end
  return false
end

local content_top_v -- forward

local function glyph_size(n)
  local f = font.getfont(n.font)
  return f and f.size or 0
end

-- largest glyph directly in an hlist (not in nested boxes)
local function direct_glyph_size(list)
  local m = 0
  for n in node.traverse_id(GLYPH, list) do
    local s = glyph_size(n)
    if s > m then
      m = s
    end
  end
  return m
end

-- topmost visible content of an hlist whose baseline is at `base`;
-- returns top, largest glyph size seen
local function content_top_h(box, base, ctx)
  local list = box.head or box.list
  if not list then
    return nil, 0
  end
  local maxsize = direct_glyph_size(list)
  ctx = ctx or 0   -- text size of the enclosing line, for nested markers
  local top = nil
  if maxsize > 0 then
    top = base - math.floor(ASCENDER * maxsize)
  end
  for n in node.traverse(list) do
    local t = nil
    if n.id == RULE then
      local h = n.height
      if h ~= -1073741824 and n.width ~= 0 and (h + n.depth) > 0 then
        t = base - h
      end
    elseif (n.id == HLIST or n.id == VLIST) and n.height + n.depth >= MIN_SIZE then
      local shift = n.shift or 0
      local nb = base + shift
      if is_picture(n) then
        -- a small picture in a text line (the bullet dot) doesn't set its top
        if not (maxsize > 0 and n.height + n.depth < SMALL_PICTURE) then
          t = nb - n.height
        end
      elseif n.id == HLIST then
        local ref = math.max(maxsize, ctx)
        local inner, size = content_top_h(n, nb, ref)
        -- a raised, smaller box (footnote marker, superscript) doesn't set
        -- the line's top -- same rule as check_layout.py's text measure
        if not (shift < 0 and ref > 0 and size > 0 and size < 0.85 * ref) then
          t = inner
        end
        if size > maxsize and shift >= 0 then
          maxsize = size
        end
      else
        t = content_top_v(n, nb - n.height)
      end
      -- nothing measurable inside, but it draws: a picture nested deeper
      if not t and not (maxsize > 0 and n.height + n.depth < SMALL_PICTURE) and draws(n) then
        t = nb - n.height
      end
    end
    if t and (not top or t < top) then
      top = t
    end
  end
  return top, maxsize
end

-- topmost visible content of a vlist whose top edge is at `y`
content_top_v = function(box, y)
  local cur = y
  local list = box.head or box.list
  if not list then
    return nil
  end
  for n in node.traverse(list) do
    if n.id == HLIST or n.id == VLIST then
      if n.height + n.depth >= MIN_SIZE then
        local t
        if is_picture(n) then
          t = cur
        elseif n.id == HLIST then
          t = content_top_h(n, cur + n.height)
        else
          t = content_top_v(n, cur)
        end
        if not t and draws(n) then
          t = cur                -- a picture nested deeper
        end
        if t then
          return t
        end
      end
      cur = cur + n.height + n.depth
    elseif n.id == RULE then
      if n.width ~= 0 and n.height + n.depth > 0 then
        return cur
      end
      cur = cur + n.height + n.depth
    elseif n.id == GLUE then
      cur = cur + node.effective_glue(n, box)
    elseif n.id == KERN then
      cur = cur + n.kern
    end
  end
  return nil
end

-- does this box contain one of our markers (anywhere inside)?
local function has_marker(box)
  local list = box.head or box.list
  if not list then
    return false
  end
  for n in node.traverse(list) do
    if is_marker(n) then
      return true
    end
    if (n.id == HLIST or n.id == VLIST) and has_marker(n) then
      return true
    end
  end
  return false
end

-- The page as a flat, document-ordered list of events: markers and visible
-- items {top, bottom} (absolute sp from the shipped box's top). A box that
-- holds a marker is opened up; any other box with visible content is one
-- item (a text line, a row of columns, a minipage line, a picture).
local events_v, events_h

local function item_of(n, top_edge, base, events)
  local t
  if is_picture(n) then
    t = top_edge
  elseif n.id == HLIST then
    t = content_top_h(n, base)
  else
    t = content_top_v(n, top_edge)
  end
  if not t and draws(n) then
    t = top_edge               -- a picture nested deeper
  end
  if t then
    events[#events + 1] = { top = t, bottom = top_edge + n.height + n.depth }
  end
end

events_v = function(box, y, events)
  local cur = y
  local list = box.head or box.list
  if not list then
    return
  end
  for n in node.traverse(list) do
    if is_marker(n) then
      events[#events + 1] = { marker = n.value, y = cur }
    elseif n.id == HLIST or n.id == VLIST then
      if has_marker(n) then
        if n.id == VLIST then
          events_v(n, cur, events)
        else
          events_h(n, cur + n.height, events)
        end
      elseif n.height + n.depth >= MIN_SIZE then
        item_of(n, cur, cur + n.height, events)
      end
      cur = cur + n.height + n.depth
    elseif n.id == RULE then
      if n.width ~= 0 and n.height + n.depth > 0 then
        events[#events + 1] = { top = cur, bottom = cur + n.height + n.depth }
      end
      cur = cur + n.height + n.depth
    elseif n.id == GLUE then
      cur = cur + node.effective_glue(n, box)
    elseif n.id == KERN then
      cur = cur + n.kern
    end
  end
end

-- An hlist holding a marker: a page-level container, or the frame's last
-- text line when the body ends inside a paragraph (the end marker then
-- lands in that line). Its own glyphs/rules become an item emitted before
-- the next marker, so the line still counts as body content; boxes without
-- markers inside it (footnotes, the footer, ...) are items of their own.
events_h = function(box, base, events)
  local list = box.head or box.list
  if not list then
    return
  end
  local pending = nil
  local maxsize = 0
  local function flush()
    if maxsize > 0 then
      local t = base - math.floor(ASCENDER * maxsize)
      if not pending or t < pending.top then
        pending = { top = t, bottom = base + box.depth }
      end
    end
    if pending then
      events[#events + 1] = pending
    end
    pending, maxsize = nil, 0
  end
  for n in node.traverse(list) do
    if is_marker(n) then
      flush()
      events[#events + 1] = { marker = n.value, y = base }
    elseif n.id == GLYPH then
      local s = glyph_size(n)
      if s > maxsize then
        maxsize = s
      end
    elseif n.id == RULE then
      if n.height ~= -1073741824 and n.width ~= 0 and n.height + n.depth > 0 then
        local t = base - n.height
        if not pending or t < pending.top then
          pending = { top = t, bottom = base + n.depth }
        end
      end
    elseif n.id == HLIST or n.id == VLIST then
      local nb = base + (n.shift or 0)
      if has_marker(n) then
        flush()
        if n.id == VLIST then
          events_v(n, nb - n.height, events)
        else
          events_h(n, nb, events)
        end
      elseif n.height + n.depth >= MIN_SIZE then
        flush()
        item_of(n, nb - n.height, nb, events)
      end
    end
  end
  flush()
end

-- one frame's numbers from a page: first content top, content bottom (the
-- end marker), and the top of the first thing after it (footnotes/footer)
local function measure_events(events)
  local index, top, bottom, after = nil, nil, nil, nil
  local state = "before"
  for _, e in ipairs(events) do
    if e.marker then
      if e.marker > 0 and state == "before" then
        index, state = e.marker, "body"
      elseif index and e.marker == -index and state == "body" then
        state = "after"
      end
    elseif state == "body" then
      if not top then
        top = e.top
      end
      if not bottom or e.bottom > bottom then
        bottom = e.bottom
      end
    elseif state == "after" and not after then
      after = e.top
    end
  end
  return index, top, bottom, after
end

local function to_bp(sp)
  -- page coordinates: the shipped box's top edge sits at 1in + \voffset
  return ((sp + tex.voffset) / SP_PER_PT + 72.27) * BP_PER_PT
end

-- shipout: measure this page. The last page of a frame wins (its final
-- overlay state).
function gotham_layout.top_measure_page(box)
  local events = {}
  if box.id == VLIST then
    events_v(box, 0, events)
  else
    events_h(box, box.height, events)
  end
  local index, top, bottom, after = measure_events(events)
  if gotham_layout.top_debug then
    for _, e in ipairs(events) do
      if e.marker then
        texio.write_nl("log", string.format("  [ev] marker %d", e.marker))
      else
        texio.write_nl("log", string.format("  [ev] item top %.2fbp bottom %.2fbp", to_bp(e.top), to_bp(e.bottom)))
      end
    end
  end
  if index and top then
    local m = { top = to_bp(top) }
    if bottom and after then
      -- room below the content, down to the footnotes/footer
      m.room = to_bp(after) - to_bp(bottom)
    end
    gotham_layout.top_measured[index] = m
    if gotham_layout.top_debug then
      texio.write_nl("log", string.format("gotham top margin: frame %d first content at %.3fbp, room below %s",
        index, m.top, m.room and string.format("%.2fbp", m.room) or "?"))
    end
  end
end

-- \AtEndDocument: the new corrections, written through TeX (\write) to
-- \jobname.top, which TeX opened in the aux directory latexmk uses
function gotham_layout.top_emit()
  local keys = {}
  for index in pairs(gotham_layout.top_applied) do
    keys[#keys + 1] = index
  end
  table.sort(keys)
  for _, index in ipairs(keys) do
    local applied = gotham_layout.top_applied[index]
    local measured = gotham_layout.top_measured[index]
    local value = applied
    if measured then
      local delta_pt = (measured.top - TOP_MARGIN_BP) / BP_PER_PT
      -- delta < 0: content too high, it moves down -- but never by more
      -- than the room left above the footnotes/footer (minus MIN_ROOM): a
      -- full slide stays where it fits instead of running into the footer
      if delta_pt < 0 and measured.room then
        local room_pt = measured.room / BP_PER_PT - MIN_ROOM_PT
        if -delta_pt > room_pt then
          delta_pt = -math.max(room_pt, 0)
        end
      end
      if math.abs(delta_pt) >= 0.01 then
        value = applied + delta_pt
      end
    end
    if math.abs(value) >= 0.0005 then
      tex.sprint(string.format(
        "\\immediate\\write\\csname SM@topfile\\endcsname"
        .. "{\\string\\SMSetTopCorrection{%d}{%.3fpt}}", index, value))
    end
  end
end

return gotham_layout
