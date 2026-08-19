' =====================================================================
'  ResearchMate.vbs - Launch ResearchMate with NO window at all.
'  Double-click this file:
'    1. starts backend\ResearchMate.exe in the background (no console)
'    2. waits until the service is ready (first run ~5-10s)
'    3. opens the app window (Edge/Chrome app mode = native app look)
'  Fully invisible: no black cmd window ever appears.
'  To quit the app: double-click stop.bat.
' =====================================================================
Dim shell, fso, here
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)

If fso.FileExists(here & "\start.bat") Then
  shell.CurrentDirectory = here
  ' 0 = hidden window, False = do not wait (script exits immediately)
  shell.Run """" & here & "\start.bat""", 0, False
Else
  MsgBox "start.bat not found next to this file. " & _
         "Please keep the original folder structure.", 16, "ResearchMate"
End If

Set shell = Nothing
Set fso = Nothing
