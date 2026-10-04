--[[
  Connection Test — checks every link in the chain and names the broken one.

  Menu: Workspace > Scripts > Figma Fusion Bridge - Connection Test
  Visible on every page.
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
local w, h = 0, 0
if c then w, h = ffb.comp_size(c) end

local out, err = ffb.run_cli("test --width " .. w .. " --height " .. h)
if not out then
  print(err)
  return
end
ffb.print_report(out)

if c then
  print("  Fusion       composition open at " .. w .. "x" .. h)
  print("  Placement    " .. ((bmd ~= nil and bmd.readfile ~= nil) and "fast path available"
                              or "fallback (file import)"))
else
  print("  Fusion       no composition open — open a clip on the Fusion page")
end
