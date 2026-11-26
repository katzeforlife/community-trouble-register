CTR = CTR or {}
CTR.StatusCache = {}

local function validSteamID64(steamid)
    return tostring(steamid or ""):match("^7656119%d%d%d%d%d%d%d%d%d%d$") ~= nil
end

function CTR.CheckSteamID(steamid64, callback)
    if not validSteamID64(steamid64) then
        if callback then callback(nil, "invalid_steamid") end
        return
    end

    local now = os.time()
    local cached = CTR.StatusCache[steamid64]
    if cached and now - cached.time < CTR.Config.StatusCacheSeconds then
        if callback then callback(cached.data, nil) end
        return
    end

    CTR.Request("GET", "/api/v1/players/" .. steamid64 .. "/status", nil, function(success, code, data)
        if success and code == 200 and data then
            CTR.StatusCache[steamid64] = {time = now, data = data}
            if callback then callback(data, nil) end
        else
            if callback then callback(nil, "api_unavailable") end
        end
    end)
end

hook.Add("PlayerAuthed", "CTR_CheckPlayerStatus", function(ply, steamid64)
    if not CTR.Config.CheckOnJoin then return end
    CTR.CheckSteamID(steamid64, function(data, error)
        if not IsValid(ply) then return end
        if error then
            CTR.Log("WARN", "Status check unavailable for " .. tostring(steamid64))
            if CTR.GetConfig().FailClosed then
                ply:Kick("CTR moderation check unavailable. Please reconnect later.")
            end
            return
        end
        if data and data.globally_banned then
            local ban = data.ban or {}
            local expiry = ban.expires_at and ("\nExpires: " .. ban.expires_at) or "\nThis is a permanent ban."
            ply:Kick("CTR global ban: " .. tostring(ban.reason or "Confirmed moderation action") .. expiry)
            CTR.Log("INFO", "Kicked globally banned SteamID64 " .. tostring(steamid64))
        end
    end)
end)
