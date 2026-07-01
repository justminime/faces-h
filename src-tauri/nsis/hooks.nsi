; Custom NSIS hooks for faces-h
;
; Two responsibilities:
;   1. Terminate any running faces-h app + sidecar before copying files, so an
;      in-place upgrade doesn't fail on a locked faces-sidecar.exe. Tauri's own
;      running-app check closes faces-h.exe, but the Python sidecar is a separate
;      process it doesn't know about, so we kill it explicitly here.
;   2. Add a Windows Defender exclusion for the sidecar exe so it isn't re-scanned
;      on every launch, which otherwise adds a long startup delay while Defender
;      inspects the new/changed binary.
;
; User data (the SQLite DB, models, and logs) lives in the per-user app-data
; directory (%APPDATA%\com.faces-h.app), NOT under $INSTDIR. The uninstaller
; below only removes the install directory + Defender exclusion and deliberately
; never touches %APPDATA%, so upgrades and uninstall/reinstall preserve the
; user's named people and scanned library.

!macro customInstall
  ; Stop a running instance so files aren't locked during an in-place upgrade.
  nsExec::ExecToLog 'taskkill /F /T /IM faces-sidecar.exe'
  nsExec::ExecToLog 'taskkill /F /T /IM faces-h.exe'
  Sleep 500

  ; Add Defender exclusion for the installed sidecar binary.
  ; Runs with admin rights because installMode is perMachine.
  nsExec::ExecToLog 'powershell.exe -NonInteractive -WindowStyle Hidden \
    -Command "Add-MpPreference -ExclusionPath \
    \"$INSTDIR\faces-sidecar.exe\" -ErrorAction SilentlyContinue"'
!macroend

!macro customUnInstall
  ; Stop a running instance so the uninstaller can remove files cleanly.
  nsExec::ExecToLog 'taskkill /F /T /IM faces-sidecar.exe'

  ; Remove the Defender exclusion.
  nsExec::ExecToLog 'powershell.exe -NonInteractive -WindowStyle Hidden \
    -Command "Remove-MpPreference -ExclusionPath \
    \"$INSTDIR\faces-sidecar.exe\" -ErrorAction SilentlyContinue"'

  ; NOTE: user data in %APPDATA%\com.faces-h.app is intentionally left in place
  ; so the library survives uninstall/reinstall. Do not add RMDir on it here.
!macroend
