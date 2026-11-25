-- Community Trouble Register (CTR) - server-side example only.
-- Keep API keys on the dedicated server; never distribute this file client-side.
-- Test on a private server before enabling any automated enforcement.

CTR = CTR or {}
CTR.Config = CTR.Config or {
    BaseURL = "http://127.0.0.1:8000",
    APIKey = "REPLACE_WITH_SERVER_API_KEY",
    CheckOnJoin = true,
    KickOnConfirmedRecord = false, -- keep false until your policy and review process are ready
}

local function CTR_Request(path, callback)
    http.Fetch(
        CTR.Config.BaseURL .. path,
        function(body, size, headers, code)
            local data = util.JSONToTable(body or "")
            if callback then callback(data, code, body) end
        end,
        function(err)
            print("[CTR] Request failed: " .. tostring(err))
            if callback then callback(nil, 0, err) end
        end,
        {
            ["X-API-Key"] = CTR.Config.APIKey,
            ["User-Agent"] = "CTR-GMod/0.1"
        }
    )
end

function CTR.CheckSteamID(steamid64, callback)
    if not string.match(steamid64 or "", "^7656119%d%d%d%d%d%d%d%d%d%d$") then
        if callback then callback(nil) end
        return
    end
    CTR_Request("/api/v1/players/" .. steamid64 .. "/status", callback)
end

hook.Add("PlayerAuthed", "CTR_CheckPlayerStatus", function(ply, steamid64)
    if not CTR.Config.CheckOnJoin then return end
    CTR.CheckSteamID(steamid64, function(data, code)
        if not IsValid(ply) or not data then return end
        if data.status and CTR.Config.KickOnConfirmedRecord then
            -- Do not enable this until your server policy clearly defines enforcement.
            ply:Kick("A confirmed community moderation record exists. Contact the server administrators for review.")
        elseif data.status then
            print("[CTR] Confirmed record found for " .. steamid64 .. "; no automatic action configured.")
        end
    end)
end)

print("[CTR] Server module loaded. Configure BaseURL and APIKey in ctr_init.lua.")
