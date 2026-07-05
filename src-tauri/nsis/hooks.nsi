; Custom NSIS hooks for faces-h
;
; IMPORTANT: Tauri 2's NSIS template only invokes macros named
; NSIS_HOOK_PREINSTALL / NSIS_HOOK_POSTINSTALL / NSIS_HOOK_PREUNINSTALL /
; NSIS_HOOK_POSTUNINSTALL. (The previous customInstall/customUnInstall names
; are electron-builder conventions and were silently never executed — #119.)
;
; Responsibilities:
;   1. PREINSTALL: terminate any running faces-h app + sidecar before copying
;      files, so an in-place upgrade doesn't fail on a locked faces-sidecar.exe.
;      Tauri's own running-app check closes faces-h.exe, but the Python sidecar
;      is a separate process it doesn't know about, so we kill it explicitly.
;   2. POSTINSTALL: add a Windows Defender exclusion for the installed sidecar
;      exe so it isn't re-scanned on every launch, which otherwise adds a long
;      startup delay while Defender inspects the new/changed binary.
;
; User data (the SQLite DB, models, and logs) lives in the per-user app-data
; directory (%APPDATA%\com.faces-h.app), NOT under $INSTDIR. The uninstall hook
; below only stops processes + removes the Defender exclusion and deliberately
; never touches %APPDATA%, so upgrades and uninstall/reinstall preserve the
; user's named people and scanned library.

!macro NSIS_HOOK_PREINSTALL
  ; Stop a running instance so files aren't locked during an in-place upgrade.
  nsExec::ExecToLog 'taskkill /F /T /IM faces-sidecar.exe'
  nsExec::ExecToLog 'taskkill /F /T /IM faces-h.exe'
  Sleep 500
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Add Defender exclusion for the installed sidecar binary.
  ; Runs with admin rights because installMode is perMachine.
  ; NSIS has no line continuation inside strings — keep this on one line.
  nsExec::ExecToLog `powershell.exe -NonInteractive -WindowStyle Hidden -Command "Add-MpPreference -ExclusionPath '$INSTDIR\faces-sidecar.exe' -ErrorAction SilentlyContinue"`
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; Stop a running instance so the uninstaller can remove files cleanly.
  nsExec::ExecToLog 'taskkill /F /T /IM faces-sidecar.exe'
  nsExec::ExecToLog 'taskkill /F /T /IM faces-h.exe'
  Sleep 500

  ; Remove the Defender exclusion.
  nsExec::ExecToLog `powershell.exe -NonInteractive -WindowStyle Hidden -Command "Remove-MpPreference -ExclusionPath '$INSTDIR\faces-sidecar.exe' -ErrorAction SilentlyContinue"`

  ; NOTE: user data in %APPDATA%\com.faces-h.app is intentionally left in place
  ; so the library survives uninstall/reinstall. Do not add RMDir on it here.
!macroend
