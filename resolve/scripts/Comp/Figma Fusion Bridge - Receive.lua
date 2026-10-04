--[[
  Receive — brings the latest design from Figma into this composition.

  Menu: Workspace > Scripts > Figma Fusion Bridge - Receive
  Visible on the Fusion page only.

  Nothing touches the composition until the whole graph has been built and
  validated, so a failed transfer leaves your work exactly as it was.
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
local out, err = ffb.run_cli("build --width " .. w .. " --height " .. h)
if not out then
  print(err)
  return
end
ffb.print_report(out)

local status = ffb.result_field(out, "status")
if status == "empty" then return end
if status ~= "ok" then
  print("Nothing was placed. Fix the errors above and send again.")
  return
end

local setting = ffb.result_field(out, "setting")
if not setting then
  print("The helper did not report a composition file.")
  return
end

local placed, perr = ffb.place(c, setting)
if placed then
  print("  Placed " .. tostring(ffb.result_field(out, "nodes")) .. " nodes into this composition.")
else
  print("  Could not place the nodes automatically: " .. tostring(perr))
  print("  The composition was saved here — drag it into the node graph:")
  print("  " .. setting)
end
