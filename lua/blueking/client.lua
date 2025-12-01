local config = require("blueking.config")
local peripherals = require("blueking.peripherals")
local commands = require("blueking.commands")

local function sendRegistration(ws)
    local regEvent = {
        type = "register",
        id = os.getComputerID(),
        capabilities = peripherals.currentCapabilities()
    }
    print("[GESTALT] Sending registration: " .. textutils.serialiseJSON(regEvent))
    ws.send(textutils.serialiseJSON(regEvent))
end

local function handleWebsocketMessage(ws, message)
    print("[GESTALT] Received message: " .. message)

    local ok, data = pcall(textutils.unserialiseJSON, message)
    if ok and data then
        commands.execute(ws, data)
    else
        print("[ERROR] Failed to parse message: " .. tostring(data))
    end
end

local function run()
    print("[GESTALT] Client v" .. config.version)

    peripherals.refreshChatBox()

    while true do
        print("[GESTALT] Connecting to " .. config.server_url .. "...")
        http.websocketAsync(config.server_url)

        local ws = nil
        local connected = false
        local keepaliveTimer = nil

        while true do
            local event, p1, p2, p3, p4 = os.pullEvent()

            if event == "websocket_success" then
                if p1 == config.server_url then
                    ws = p2
                    connected = true
                    print("[GESTALT] Connected to brain!")

                    sendRegistration(ws)
                    keepaliveTimer = os.startTimer(config.keepalive_interval)
                end

            elseif event == "websocket_failure" then
                if p1 == config.server_url then
                    print("[ERROR] Connection failed: " .. tostring(p2))
                    break
                end

            elseif event == "websocket_closed" then
                if p1 == config.server_url then
                    print("[GESTALT] Connection closed")
                    connected = false
                    keepaliveTimer = nil
                    break
                end

            elseif event == "websocket_message" then
                if p1 == config.server_url then
                    handleWebsocketMessage(ws, p2)
                end

            elseif event == "chat" then
                if connected and not p4 then
                    local username, message = p1, p2
                    print("[GESTALT] Chat from " .. username .. ": " .. message)

                    local chatEvent = textutils.serialiseJSON({
                        type = "chat",
                        username = username,
                        message = message
                    })

                    print("[GESTALT] Sending chat event: " .. chatEvent)
                    ws.send(chatEvent)
                end

            elseif event == "timer" then
                if connected and keepaliveTimer and p1 == keepaliveTimer then
                    sendRegistration(ws)
                    keepaliveTimer = os.startTimer(config.keepalive_interval)
                end
            end
        end

        print("[GESTALT] Reconnecting in " .. config.reconnect_delay .. " seconds...")
        os.sleep(config.reconnect_delay)
    end
end

return { run = run }
