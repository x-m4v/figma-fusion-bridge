-- Windows LuaJIT launcher: pass UTF-16 directly to CreateProcessW.
-- Avoids cmd.exe expansion and ANSI io.popen path handling.
local ffi_ok, ffi = pcall(require, 'ffi')
if ffi_ok then
  if not pcall(ffi.typeof, 'FFB_STARTUPINFOW') then
    ffi.cdef[[
      typedef struct { uint32_t nLength; void *lpSecurityDescriptor; int bInheritHandle; } FFB_SECURITY_ATTRIBUTES;
      typedef struct { uint32_t cb; uint16_t *lpReserved; uint16_t *lpDesktop; uint16_t *lpTitle;
        uint32_t dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
        uint16_t wShowWindow, cbReserved2; uint8_t *lpReserved2; void *hStdInput; void *hStdOutput; void *hStdError;
      } FFB_STARTUPINFOW;
      typedef struct { void *hProcess; void *hThread; uint32_t dwProcessId, dwThreadId; } FFB_PROCESS_INFORMATION;
      int MultiByteToWideChar(unsigned int, uint32_t, const char *, int, uint16_t *, int);
      int CreatePipe(void **, void **, FFB_SECURITY_ATTRIBUTES *, uint32_t);
      int SetHandleInformation(void *, uint32_t, uint32_t);
      void *CreateFileW(const uint16_t *, uint32_t, uint32_t, FFB_SECURITY_ATTRIBUTES *, uint32_t, uint32_t, void *);
      int CreateProcessW(const uint16_t *, uint16_t *, void *, void *, int, uint32_t, void *, const uint16_t *, FFB_STARTUPINFOW *, FFB_PROCESS_INFORMATION *);
      int PeekNamedPipe(void *, void *, uint32_t, uint32_t *, uint32_t *, uint32_t *);
      int ReadFile(void *, void *, uint32_t, uint32_t *, void *);
      uint32_t WaitForSingleObject(void *, uint32_t);
      int TerminateProcess(void *, unsigned int);
      int CloseHandle(void *);
      uint32_t GetLastError(void);
      uint64_t GetTickCount64(void);
      void Sleep(uint32_t);
    ]]
  end
  local win = ffi.load('kernel32')
  local function wide(text)
    local count = win.MultiByteToWideChar(65001, 8, text, #text, nil, 0)
    if count == 0 then error('Invalid UTF-8 in Windows command') end
    local buffer = ffi.new('uint16_t[?]', count + 1)
    assert(win.MultiByteToWideChar(65001, 8, text, #text, buffer, count) > 0)
    return buffer
  end

  function M.run_windows(command)
    local reader, writer = ffi.new('void *[1]'), ffi.new('void *[1]')
    local security = ffi.new('FFB_SECURITY_ATTRIBUTES')
    security.nLength = ffi.sizeof(security)
    security.bInheritHandle = 1
    if win.CreatePipe(reader, writer, security, 0) == 0 then
      return nil, 'Cannot create helper output pipe.'
    end
    win.SetHandleInformation(reader[0], 1, 0)
    local input = win.CreateFileW(wide('NUL'), 0x80000000, 3, security, 3, 0, nil)
    local startup = ffi.new('FFB_STARTUPINFOW')
    startup.cb, startup.dwFlags = ffi.sizeof(startup), 0x100
    startup.hStdInput, startup.hStdOutput, startup.hStdError = input, writer[0], writer[0]
    local process = ffi.new('FFB_PROCESS_INFORMATION')
    local created = win.CreateProcessW(nil, wide(command), nil, nil, 1, 0x08000000, nil, nil, startup, process)
    local failure = tonumber(win.GetLastError())
    win.CloseHandle(writer[0]); win.CloseHandle(input)
    if created == 0 then
      win.CloseHandle(reader[0])
      return nil, 'Cannot start bridge helper (Windows error ' .. failure .. ').'
    end
    win.CloseHandle(process.hThread)
    local deadline = tonumber(win.GetTickCount64()) + 120000
    local parts, total = {}, 0
    local available, received = ffi.new('uint32_t[1]'), ffi.new('uint32_t[1]')
    local buffer = ffi.new('uint8_t[8192]')
    local error_message = nil
    while true do
      if win.PeekNamedPipe(reader[0], nil, 0, nil, available, nil) == 0 then break end
      if available[0] > 0 then
        if win.ReadFile(reader[0], buffer, math.min(8192, tonumber(available[0])), received, nil) == 0 then break end
        total = total + tonumber(received[0])
        if total > 16 * 1024 * 1024 then error_message = 'Helper report is too large.'; break end
        parts[#parts + 1] = ffi.string(buffer, received[0])
      elseif win.WaitForSingleObject(process.hProcess, 0) == 0 then
        break
      elseif tonumber(win.GetTickCount64()) > deadline then
        error_message = 'Bridge helper timed out after two minutes.'; break
      else
        win.Sleep(10)
      end
    end
    if error_message then win.TerminateProcess(process.hProcess, 1) end
    win.CloseHandle(process.hProcess); win.CloseHandle(reader[0])
    if error_message then return nil, error_message end
    return table.concat(parts)
  end
else
  function M.run_windows()
    return nil, 'Windows requires LuaJIT (as provided by Resolve).'
  end
end
