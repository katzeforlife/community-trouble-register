CTR = CTR or {}

local function findUniquePlayer(name)
    local matches = {}
    for _, ply in ipairs(player.GetAll()) do
        if ply:SteamID64() ~= "" and string.lower(ply:Nick()) == string.lower(name) then
            table.insert(matches, ply)
        end
    end
    if #matches == 1 then return matches[1]:SteamID64() end
    return nil
end

local function parseDuration(text)
    local value = text:lower():Trim()
    if value == "permanent" or value == "perm" or value == "0" then return "permanent" end
    if value:match("^%d+[mhdw]$") then return value end
    return nil
end

local function executeBan(actorName, steamid64, duration, reason)
    if not steamid64 or not steamid64:match("^7656119%d%d%d%d%d%d%d%d%d%d$") then
        return false, "Invalid SteamID64"
    end
    if string.len(reason) < 10 then
        return false, "Ban reason must be at least 10 characters"
    end
    local parsed = parseDuration(duration)
    if not parsed then
        return false, "Invalid duration; use 7d, 24h, permanent, or another m/h/d/w duration"
    end

    CTR.Request("POST", "/api/v1/moderation/bans", {
        steamid = steamid64,
        duration = parsed,
        reason = reason,
        actor = actorName
    }, function(success, code, data)
        if success and code == 200 and data and data.confirmed then
            CTR.Log("INFO", "Confirmed global ban for " .. steamid64)
            for _, ply in ipairs(player.GetAll()) do
                if ply:SteamID64() == steamid64 then
                    ply:Kick("CTR global ban confirmed: " .. reason)
                end
            end
            print("[CTR] Global ban confirmed for " .. steamid64)
        else
            CTR.Log("ERROR", "Global ban was NOT confirmed (HTTP " .. tostring(code) .. ")")
            print("[CTR] Global ban was NOT confirmed.")
        end
    end)
    return true, "Ban request submitted; waiting for CTR confirmation"
end

concommand.Add("ctr_ban", function(ply, cmd, args)
    if IsValid(ply) and not ply:IsSuperAdmin() then
        ply:ChatPrint("[CTR] You do not have permission to issue global bans.")
        return
    end
    if #args < 3 then
        local target = IsValid(ply) and ply:ChatPrint or print
        target("[CTR] Usage: ctr_ban <SteamID64|exact username> <duration> <reason>")
        return
    end
    local target = args[1]
    local steamid64 = target
    if not steamid64:match("^7656119%d%d%d%d%d%d%d%d%d%d$") then
        steamid64 = findUniquePlayer(target)
        if not steamid64 then
            local targetFn = IsValid(ply) and ply:ChatPrint or print
            targetFn("[CTR] Username was ambiguous or not found; supply the exact SteamID64.")
            return
        end
    end
    local ok, message = executeBan(IsValid(ply) and ply:SteamID64() or "console", steamid64, args[2], table.concat(args, " ", 3))
    local targetFn = IsValid(ply) and ply:ChatPrint or print
    targetFn("[CTR] " .. message)
end)

hook.Add("PlayerSay", "CTR_BanChatCommand", function(ply, text)
    if not ply:IsSuperAdmin() then return end
    local args = string.Explode(" ", text:Trim(), false)
    if string.lower(args[1] or "") ~= "!ctr_ban" then return end
    table.remove(args, 1)
    if #args < 3 then
        ply:ChatPrint("[CTR] Usage: !ctr_ban <SteamID64|exact username> <duration> <reason>")
        return ""
    end
    local steamid64 = args[1]
    if not steamid64:match("^7656119%d%d%d%d%d%d%d%d%d%d$") then
        steamid64 = findUniquePlayer(args[1])
        if not steamid64 then
            ply:ChatPrint("[CTR] Username was ambiguous or not found; supply the exact SteamID64.")
            return ""
        end
    end
    local ok, message = executeBan(ply:SteamID64(), steamid64, args[2], table.concat(args, " ", 3))
    ply:ChatPrint("[CTR] " .. message)
    return ""
end)
