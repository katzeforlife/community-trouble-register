CTR = CTR or {}

local STATE_FILE = "ctr/server_state.json"

function CTR.LoadServerState()
    if not file.Exists(STATE_FILE, "DATA") then return nil end
    local state = util.JSONToTable(file.Read(STATE_FILE, "DATA") or "") or {}
    if state.api_key and state.api_key ~= "" then
        RunConsoleCommand("ctr_api_key", state.api_key)
    end
    if state.registration_id and state.registration_id ~= "" then
        RunConsoleCommand("ctr_registration_id", state.registration_id)
    end
    return state
end

function CTR.SaveServerState(state)
    file.CreateDir("ctr")
    file.Write(STATE_FILE, util.TableToJSON(state, true))
end

function CTR.RegisterServer(callback)
    local state = CTR.LoadServerState() or {}
    if state.api_key and state.api_key ~= "" then
        RunConsoleCommand("ctr_api_key", state.api_key)
        CTR.Log("INFO", "Using saved CTR server credential")
        if callback then callback(true, state) end
        return
    end

    local config = CTR.GetConfig()
    if config.SetupToken == "" then
        CTR.Log("WARN", "No CTR setup/pairing token configured; registration deferred")
        if callback then callback(false, nil) end
        return
    end

    CTR.Request("POST", "/api/v1/servers/register", {
        name = CTR.Config.ServerName,
        address = game.GetIPAddress(),
        game_id = "4000",
        registration_id = config.RegistrationID
    }, function(success, code, data)
        if not success or code ~= 200 or not data or not data.api_key then
            CTR.Log("WARN", "Registration failed; retrying later")
            if callback then callback(false, data) end
            return
        end
        state.api_key = data.api_key
        state.server_id = data.server_id
        state.registration_id = data.registration_id
        CTR.SaveServerState(state)
        RunConsoleCommand("ctr_api_key", data.api_key)
        RunConsoleCommand("ctr_registration_id", state.registration_id)
        CTR.Log("INFO", "Registered as CTR server " .. tostring(state.server_id) .. " (pending verification)")
        if callback then callback(true, state) end
    end)
end

function CTR.SendHeartbeat()
    local state = CTR.LoadServerState()
    if not state or not state.api_key then
        CTR.RegisterServer(function(ok)
            if ok then CTR.SendHeartbeat() end
        end)
        return
    end

    local config = CTR.GetConfig()
    CTR.Request("POST", "/api/v1/servers/heartbeat", {
        server_id = state.server_id,
        server_name = CTR.Config.ServerName,
        map = game.GetMap(),
        player_count = player.GetCount(),
        max_player_count = game.MaxPlayers(),
        gmod_version = tostring(VERSION or "")
    }, function(success, code, data)
        if success and code == 200 then
            CTR.Log("INFO", "Heartbeat sent; status=" .. tostring(data.verification_status))
        else
            CTR.Log("WARN", "Heartbeat failed")
        end
    end)
end
