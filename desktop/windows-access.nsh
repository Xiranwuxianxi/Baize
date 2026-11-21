; Chromium's restricted processes need read access to the application files.
; Apply this only to the extracted/installed program, never to user data.
Function BaizeGrantSandboxReadAccess
  nsExec::ExecToStack '"$SYSDIR\icacls.exe" "$INSTDIR" /grant "*S-1-15-2-1:(OI)(CI)(RX)"'
  Pop $R0
  Pop $R1
  StrCmp $R0 "0" baize_access_ready
  MessageBox MB_OK|MB_ICONSTOP "Baize could not prepare its application folder (Windows error $R0).$\r$\n$R1"
  SetErrorLevel 1
  Quit
  baize_access_ready:
FunctionEnd

!macro customFiles_x64
  Call BaizeGrantSandboxReadAccess
!macroend
!macro customFiles_arm64
  Call BaizeGrantSandboxReadAccess
!macroend
!macro customFiles_ia32
  Call BaizeGrantSandboxReadAccess
!macroend
