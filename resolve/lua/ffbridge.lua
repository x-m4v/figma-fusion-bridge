--[[
  Shared helper for the Figma Fusion Bridge menu commands.

  The menu commands are Lua because DaVinci Resolve ships LuaJIT but no Python:
  a `.py` file in the Scripts folder is only listed when a Python framework
  happens to be installed in a system location, so on a stock Mac the Python
  commands are invisible. Lua is always there.

  Lua does only what nothing else can do — put nodes into the open composition.
  Everything else (talking to the bridge, resolving fonts, converting the
  design) is a plain Python process with no Resolve bindings, which keeps that
  half testable without Resolve running.
]]

local M = {}

M.IS_WINDOWS = package.config:sub(1, 1) == "\\"
local base = os.getenv("FFBRIDGE_SUPPORT_DIR")
if not base or base == "" then
  if M.IS_WINDOWS then
    base = assert(os.getenv("LOCALAPPDATA"), "LOCALAPPDATA is missing") .. "/FigmaFusionBridge"
  else
    base = assert(os.getenv("HOME"), "HOME is missing") .. "/Library/Application Support/FigmaFusionBridge"
  end
end
M.LIB_DIR = M.LIB_DIR or (base .. "/lib")

local function q(s)
  s = tostring(s)
  if M.IS_WINDOWS then
    assert(not s:find('["\r\n]'), "Unsupported shell characters in path")
    return '"' .. s .. '"'
  end
  return "'" .. s:gsub("'", "'\\''") .. "'"
end
M.quote = q

function M.find_python()
  if M.RUNTIME then return M.RUNTIME end
  local config = io.open(M.LIB_DIR .. "/python-path.txt", "r")
  if config then
    local path = config:read("*l")
    config:close()
    if path and #path > 0 then return path end
  end
  if M.IS_WINDOWS then return nil end
  for _, path in ipairs({"/opt/homebrew/bin/python3", "/usr/local/bin/python3",
      "/Library/Frameworks/Python.framework/Versions/Current/bin/python3", "/usr/bin/python3"}) do
    local fh = io.open(path, "r")
    if fh then fh:close(); return path end
  end
  return nil
end

--- Run the bridge CLI and return its output.
function M.run_cli(args)
  if args:match('^build%s') then
    local ok, target = pcall(function()
      local r = bmd.scriptapp('Resolve')
      local project = assert(r:GetProjectManager():GetCurrentProject())
      local timeline = project:GetCurrentTimeline()
      local function setting(key)
        local value = timeline and timeline:GetSetting(key)
        if value == nil or value == '' then value = project:GetSetting(key) end
        return value
      end
      local science = setting('colorScienceMode')
      local space = setting('colorSpaceTimeline') or ''
      if science == 'davinciYRGB' then return 'UNMANAGED' end
      if science == 'davinciYRGBColorManagedv2' then
        if space == 'DaVinci WG/Intermediate' or space == 'DaVinci Wide Gamut' then return 'DWG_LINEAR' end
        if space:match('^Rec%.709') or space == 'sRGB' then return 'SRGB_LINEAR' end
      end
      error('Unsupported color context: '..tostring(science)..' / '..space)
    end)
    if not ok then return nil, 'Cannot determine Fusion color space: '..tostring(target) end
    args = args .. ' --fusion-color-space ' .. target
  end
  local python = M.find_python()
  if not python then
    return nil, "Python runtime is missing. Run the bridge installer again."
  end
  local command = q(python)
  if M.IS_WINDOWS and python:lower():match("%.exe$") and python:lower():find("figmafusionbridge", 1, true) then
    command = command .. " --cli "
  else
    command = command .. " " .. q(M.LIB_DIR .. "/ffbridge_launcher.py") .. " "
  end
  local cmd = command .. args .. " 2>&1"
  if M.IS_WINDOWS then
    if not M.run_windows then return nil, "Windows launcher is missing. Reinstall the scripts." end
    return M.run_windows(command .. args)
  end
  local pipe = io.popen(cmd, "r")
  if not pipe then
    return nil, "Could not start the bridge helper."
  end
  local out = pipe:read("*a") or ""
  pipe:close()
  return out
end

--- Pull one string field out of the helper's result line.
--
-- Deliberately pattern matching rather than parsing JSON: the contract is three
-- flat fields, and adding a JSON library to load inside Resolve would be more
-- to go wrong than it saves.
function M.result_field(output, key)
  local line = output:match("FFBRIDGE_RESULT ([^\n]+)")
  if not line then return nil end
  local value = line:match('"' .. key .. '"%s*:%s*"(.-)"')
       or line:match('"' .. key .. '"%s*:%s*([%d%.%-]+)')
  -- Decode the JSON escapes used in Windows paths. Unicode is emitted as UTF-8.
  if value then value = value:gsub('\\(.)', { ['\\'] = '\\', ['"'] = '"', n = '\n', r = '\r', t = '\t', ['/'] = '/' }) end
  return value
end

--- The composition to work in, whichever global Resolve provided.
function M.current_comp()
  if composition ~= nil then return composition end
  if comp ~= nil then return comp end
  if fusion ~= nil then return fusion:GetCurrentComp() end
  return nil
end

--- Composition resolution, falling back to 1080p rather than failing.
function M.comp_size(c)
  local w, h = 1920, 1080
  if c and c.GetPrefs then
    local format = c:GetPrefs("Comp.FrameFormat")
    if format then
      w = format.Width or w
      h = format.Height or h
    end
  end
  return math.floor(w), math.floor(h)
end

--- Place a built composition fragment into `c`.
--
-- Three tiers, most faithful first. The last one always works: the file is on
-- disk either way, so a user whose Fusion refuses the paste can still drag it
-- into the node graph by hand.
function M.place(c, setting_path)
  if not c then
    return false, "There is no open Fusion composition."
  end

  if c.Lock then c:Lock() end
  if c.StartUndo then c:StartUndo("Figma Fusion Bridge import") end

  -- Every attempt runs inside pcall, and unlocking happens on the way out no
  -- matter what. An error escaping here would leave the composition locked,
  -- which looks to the user like Resolve itself has broken.
  local attempt = function()
    if bmd ~= nil and bmd.readfile ~= nil then
      local settings = bmd.readfile(setting_path)
      if settings then
        -- Still images must cover the composition, not just frame zero.
        local attrs = c:GetAttrs()
        local first = attrs.COMPN_GlobalStart or 0
        local last = attrs.COMPN_GlobalEnd or first
        for _, tool in pairs(settings.Tools or {}) do
          if type(tool) == "table" and type(tool.Clips) == "table" then
            for _, clip in pairs(tool.Clips) do
              if type(clip) == "table" then
                clip.GlobalStart = first
                clip.GlobalEnd = last
                clip.ExtendLast = math.max(0, last - first)
                clip.Loop = 0
              end
            end
          end
        end
        local existing = {}
        for _, tool in pairs(c:GetToolList(false)) do
          existing[tool:GetAttrs().TOOLS_Name] = true
        end
        local pasted = c:Paste(settings)
        if pasted == true then
          for _, tool in pairs(c:GetToolList(false)) do
            local ta = tool:GetAttrs()
            if not existing[ta.TOOLS_Name] and ta.TOOLS_RegID == "Loader" then
              local paths = ta.TOOLST_Clip_Name or {}
              if paths[1] then
                -- Initialise the media via the native input so the Loader's
                -- clip state and inspector values agree (Resolve 21).
                tool:SetInput("Clip", paths[1])
                tool:SetInput("Loop", 0)
                tool:SetInput("GlobalIn", first)
                tool:SetInput("HoldLastFrame", math.max(0, last - first))
              end
            end
          end
        end
        if pasted ~= false then return true, nil end
        return false, "Fusion did not accept the composition."
      end
      return false, "The composition file could not be read."
    end
    return false, "This build of Fusion does not expose bmd.readfile."
  end

  local called, ok, err = pcall(attempt)
  if not called then
    err = "Fusion raised an error while placing the nodes: " .. tostring(ok)
    ok = false
  end

  -- Never retry a partially completed native operation with a different type.
  -- pcall catches Lua errors only; native renderer crashes require graph fixes.
  if c.EndUndo then pcall(function() c:EndUndo(ok == true) end) end
  if c.Unlock then pcall(function() c:Unlock() end) end

  return ok, err
end

--- Print the helper's report, minus the machine-readable line.
function M.print_report(output)
  for line in tostring(output):gmatch("([^\n]*)\n?") do
    if line ~= "" and not line:match("^FFBRIDGE_RESULT") then
      print(line)
    end
  end
end

return M
