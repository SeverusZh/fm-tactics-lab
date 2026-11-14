; Stops the desktop shell and its sidecar before the installer copies or removes files.
; A running sidecar keeps handles on its own directory, so the installer skips
; those files and leaves the desktop shell and sidecar on different versions.
; The desktop shell is stopped first: it supervises the sidecar and would restart
; a sidecar that disappears underneath it.
!macro FM27LAB_STOP_PROCESSES
  nsExec::Exec 'taskkill /F /T /IM fm27lab-desktop.exe'
  Pop $0
  nsExec::Exec 'taskkill /F /T /IM fm27lab-sidecar.exe'
  Pop $0
  Sleep 1500
!macroend

!macro NSIS_HOOK_PREINSTALL
  !insertmacro FM27LAB_STOP_PROCESSES
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  !insertmacro FM27LAB_STOP_PROCESSES
!macroend
