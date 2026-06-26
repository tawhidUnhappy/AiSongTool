; Custom NSIS include — auto-discovered by electron-builder as
; `buildResourcesDir/installer.nsh` (no `nsis.include` config needed, see
; NsisTarget.js's `packager.getResource(this.options.include, "installer.nsh")`).
;
; `customInit` is a hook electron-builder's own installer.nsi calls from
; inside its `Function .onInit`, right after `initMultiUser` (which sets up
; SHELL_CONTEXT/per-machine detection) — see that file's line ~79
; (`!ifmacrodef customInit / !insertmacro customInit`). We can't define our
; own `Function .onInit` here: installer.nsi already defines one, and NSIS
; doesn't allow two functions with the same name.
;
; Reads the version this machine already has installed (the exact
; registry value electron-builder itself writes on every install —
; `WriteRegStr SHELL_CONTEXT "${UNINSTALL_REGISTRY_KEY}" "DisplayVersion"
; "${VERSION}"` in templates/nsis/include/installer.nsh) and compares it to
; this installer's own bundled ${VERSION}:
;   - no existing install (empty read)        -> proceed silently
;   - same version already installed          -> ask before reinstalling
;   - different version (upgrade or downgrade) -> proceed silently; the
;     stock upgrade flow already preserves the app's data folder (see
;     uninstaller.nsh's `${ifNot} ${isUpdated}` guard around
;     deleteAppDataOnUninstall — only a real user-invoked uninstall, never
;     this upgrade path, passes without `--updated`).
!macro customInit
  ReadRegStr $R0 SHELL_CONTEXT "${UNINSTALL_REGISTRY_KEY}" "DisplayVersion"
  ${if} $R0 != ""
  ${andIf} $R0 == "${VERSION}"
    MessageBox MB_YESNO|MB_ICONQUESTION "${PRODUCT_NAME} ${VERSION} is already installed.$\r$\n$\r$\nReinstall anyway?" IDYES customInit_proceed
    Quit
    customInit_proceed:
  ${endIf}
!macroend
