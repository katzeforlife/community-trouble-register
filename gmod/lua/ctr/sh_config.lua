CTR = CTR or {}
CTR.Config = {
    BaseURL = "https://community-trouble-register.onrender.com",
    SetupToken = "",
    APIKey = "",
    ServerName = GetHostName and GetHostName() or "Garrys Mod Server",
    RegistrationID = "",
    HeartbeatInterval = 300,
    StatusCacheSeconds = 30,
    APITimeout = 10,
    FailClosed = false,
    CheckOnJoin = true,
    LogToConsole = true
}

-- Server owners may override these server-only convars in server.cfg.
CreateConVar("ctr_api_url", CTR.Config.BaseURL, FCVAR_ARCHIVE, "CTR API base URL")
CreateConVar("ctr_api_key", CTR.Config.APIKey, FCVAR_ARCHIVE, "CTR server API key")
CreateConVar("ctr_registration_id", CTR.Config.RegistrationID, FCVAR_ARCHIVE, "CTR persistent registration ID")
CreateConVar("ctr_setup_token", CTR.Config.SetupToken, FCVAR_ARCHIVE, "CTR setup/pairing token")
CreateConVar("ctr_fail_closed", "0", FCVAR_ARCHIVE, "Fail closed when CTR cannot be reached")
CreateConVar("ctr_heartbeat_interval", tostring(CTR.Config.HeartbeatInterval), FCVAR_ARCHIVE, "CTR heartbeat seconds")
