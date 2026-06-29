; Custom NSIS hooks for faces-h
;
; Add a Windows Defender exclusion for the sidecar exe so it is not
; re-scanned on every upgrade, eliminating the 10-30s startup delay
; that occurs when Defender inspects a new/changed binary.

!macro customInstall
  ; Add Defender exclusion for the installed sidecar binary.
  ; Runs with admin rights because installMode is perMachine.
  nsExec::ExecToLog 'powershell.exe -NonInteractive -WindowStyle Hidden \
    -Command "Add-MpPreference -ExclusionPath \
    \"$INSTDIR\faces-sidecar.exe\" -ErrorAction SilentlyContinue"'
!macroend

!macro customUnInstall
  ; Remove the exclusion when the app is uninstalled.
  nsExec::ExecToLog 'powershell.exe -NonInteractive -WindowStyle Hidden \
    -Command "Remove-MpPreference -ExclusionPath \
    \"$INSTDIR\faces-sidecar.exe\" -ErrorAction SilentlyContinue"'
!macroend
