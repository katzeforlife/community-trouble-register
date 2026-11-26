CTR = CTR or {}

function CTR.ConfigValue(name)
    local value = GetConVarString(name)
    if value and value ~= "" then return value end
    return nil
end

function CTR.GetConfig()
    return {
        BaseURL = (CTR.ConfigValue("ctr_api_url") or CTR.Config.BaseURL):Trim():gsub("/$", ""),
        APIKey = CTR.ConfigValue("ctr_api_key") or "",
        SetupToken = CTR.ConfigValue("ctr_setup_token") or "",
        RegistrationID = CTR.ConfigValue("ctr_registration_id") or "",
        HeartbeatInterval = math.max(30, tonumber(CTR.ConfigValue("ctr_heartbeat_interval")) or CTR.Config.HeartbeatInterval),
        FailClosed = GetConVarNumber("ctr_fail_closed") == 1
    }
end

function CTR.Request(method, path, body, callback)
    local config = CTR.GetConfig()
    local headers = {
        ["Content-Type"] = "application/json",
        ["User-Agent"] = "CTR-GMod/1.0"
    }
    if config.APIKey ~= "" then headers["X-API-Key"] = config.APIKey end
    if config.SetupToken ~= "" then headers["X-Setup-Token"] = config.SetupToken end

    HTTP({
        method = method,
        url = config.BaseURL .. path,
        headers = headers,
        body = body and util.TableToJSON(body) or nil,
        timeout = CTR.Config.APITimeout,
        success = function(code, response)
            local data = util.JSONToTable(response or "") or {}
            if callback then callback(true, code, data, response) end
        end,
        failed = function(reason)
            CTR.Log("ERROR", "API request failed: " .. tostring(reason))
            if callback then callback(false, 0, nil, reason) end
        end
    })
end
