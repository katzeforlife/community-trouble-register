-- CTR server-side integration bootstrap.
-- Secret values must be set with server-only convars, never workshop/client Lua.

AddCSLuaFile()
include("ctr/sh_config.lua")
include("ctr/sv_logging.lua")
include("ctr/sv_api.lua")
include("ctr/sv_registration.lua")
include("ctr/sv_player_check.lua")
include("ctr/sv_commands.lua")

CTR.Log("INFO", "Addon initialized")
CTR.RegisterServer(function()
    timer.Create("CTRHeartbeat", CTR.GetConfig().HeartbeatInterval, 0, CTR.SendHeartbeat)
    CTR.SendHeartbeat()
end)
