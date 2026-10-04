--[[
  Pull Current Figma Selection — fetches whatever is selected in Figma right now.

  Menu: Workspace > Scripts > Figma Fusion Bridge - Pull Figma Selection
  Visible on the Fusion page only.

  Lets you stay in Resolve: the bridge asks the running plugin for its current
  selection, so there is no need to switch to Figma and press Send.
]]

local base = os.getenv("FFBRIDGE_SUPPORT_DIR")
if not base or base == "" then
  if package.config:sub(1, 1) == "\\" then
    base = assert(os.getenv("LOCALAPPDATA"), "LOCALAPPDATA is missing") .. "/FigmaFusionBridge"
  else
    base = assert(os.getenv("HOME"), "HOME is missing") .. "/Library/Application Support/FigmaFusionBridge"
  end
end
local ok, ffb = pcall(dofile, base .. "/lib/ffbridge.lua")
if not ok or not ffb then
  print("Figma Fusion Bridge is not installed correctly.")
  print("Run the bridge installer again to repair it.")
  return
end

local c = ffb.current_comp()
if not c then
  print("Open a clip on the Fusion page first, then run this again.")
  return
end

local w, h = ffb.comp_size(c)
local out, err = ffb.run_cli("build --pull --width " .. w .. " --height " .. h)
if not out then
  print(err)
  return
end
ffb.print_report(out)

if ffb.result_field(out, "status") ~= "ok" then return end

local setting = ffb.result_field(out, "setting")
if not setting then return end

local placed, perr = ffb.place(c, setting)
if placed then
  print("  Placed " .. tostring(ffb.result_field(out, "nodes")) .. " nodes into this composition.")
else
  print("  Could not place the nodes automatically: " .. tostring(perr))
  print("  " .. setting)
end
