CTR = CTR or {}

function CTR.Log(level, message)
    if CTR.Config and CTR.Config.LogToConsole == false then return end
    print(string.format("[CTR %s] %s", string.upper(level or "INFO"), tostring(message)))
end
