Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)

Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = currentDir

batPath = currentDir & "\start_dev_web.bat"
WshShell.Run """" & batPath & """ --log", 0, False
