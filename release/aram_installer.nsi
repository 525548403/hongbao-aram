; ARAM Score - NSIS installer template
; ============================================================
; Build:  install NSIS (https://nsis.sourceforge.io), then run:
;           makensis aram_installer.nsi
; Output:  ARAM-Score-Setup.exe  (a real Windows setup program)
;
; Note: this file uses English strings to avoid encoding issues.
; If you want a Chinese installer UI, save this file as UTF-8 WITH BOM
; and keep "Unicode true" enabled (already set below).
; The .exe (aram_score.exe) must sit next to this .nsi when compiling.
; ============================================================
Unicode true

!define APPNAME "ARAM Score"
!define EXE     "aram_score.exe"
!define VERSION "1.1.0"

; Install to LocalAppData so no admin rights are required
InstallDir "$LOCALAPPDATA\Programs\${APPNAME}"

RequestExecutionLevel user

Name "${APPNAME}"
OutFile "ARAM-Score-Setup.exe"
Compression lzma
SetCompressor /SOLID lzma

!include "MUI2.nsh"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "Install"
  SetOutPath "$INSTDIR"
  File "${EXE}"
  File "README.txt"

  ; Start Menu shortcut
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\${EXE}"
  ; Desktop shortcut
  CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${EXE}"

  WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\${EXE}"
  Delete "$INSTDIR\README.txt"
  Delete "$INSTDIR\Uninstall.exe"
  Delete "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
  RMDir "$SMPROGRAMS\${APPNAME}"
  Delete "$DESKTOP\${APPNAME}.lnk"
  RMDir "$INSTDIR"
SectionEnd
