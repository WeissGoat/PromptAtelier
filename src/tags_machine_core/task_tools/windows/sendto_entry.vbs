Option Explicit

Dim shell, command, argument
Set shell = CreateObject("WScript.Shell")

Function QuoteArgument(value)
    QuoteArgument = """" & Replace(CStr(value), """", """""") & """"
End Function

command = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass" & _
          " -File ""{bootstrap_path}"" -Mode ""{mode}""{operation_argument}"

For Each argument In WScript.Arguments
    command = command & " " & QuoteArgument(argument)
Next

shell.Run command, 0, False
