-- gestalt.lua
-- GESTALT Client - Bridge to Rust Brain
-- Version: 3.2.0 (WebSocket + Result Reporting)

local VERSION = "0.2.0"
local SERVER_URL = "ws://192.168.50.176:3000/api/ws" -- Adjust if running on a different machine
local BOT_NAME = "Gestalt"
local RECONNECT_DELAY = 5
local KEEPALIVE_INTERVAL = 60

-- =================
-- PERIPHERAL MGR
-- =================

local chatBox = nil

local function refreshChatBox()
    local found = peripheral.find("chatBox") or peripheral.find("chat_box")
    if found ~= chatBox then
        chatBox = found
        if chatBox then
            print("[GESTALT] ChatBox found: " .. peripheral.getName(chatBox))
        else
            print("[WARNING] No ChatBox found")
        end
    end
end

local function currentCapabilities()
    refreshChatBox()
    return chatBox and { "chat" } or {}
end

local function sendMessage(message)
    if chatBox then
        print("[GESTALT] Sending chat message: " .. message)
        chatBox.sendMessage(message, BOT_NAME)
        return true
    else
        print("[ERROR] No chatBox found")
        return false
    end
end

-- =================
-- COMMAND EXECUTION
-- =================

local function executeCommand(ws, command)
    print("[GESTALT] Executing command: " .. command.name .. " (id: " .. command.id .. ")")

    local errorMsg = nil

    if command.name == "message" then
        local ok, result = pcall(function()
            return sendMessage(command.args.message)
        end)

        if ok and result then
            -- Sent successfully
            errorMsg = nil
        elseif ok then
            errorMsg = "Failed to send message (no chatBox)"
        else
            errorMsg = tostring(result)
        end
    else
        errorMsg = "Unknown command: " .. command.name
    end

    -- Send result back to server
    local resultEvent = {
        type = "command_result",
        command_id = command.id,
        error = errorMsg
    }

    local resultJson = textutils.serialiseJSON(resultEvent)
    print("[GESTALT] Sending command result: " .. resultJson)
    ws.send(resultJson)
end

-- =================
-- MAIN LOOP
-- =================

local function main()
    print("[GESTALT] Client v" .. VERSION)

    refreshChatBox()

    while true do
        print("[GESTALT] Connecting to " .. SERVER_URL .. "...")
        http.websocketAsync(SERVER_URL)

        local ws = nil
        local connected = false
        local keepaliveTimer = nil

        while true do
            local event, p1, p2, p3 = os.pullEvent()

            if event == "websocket_success" then
                if p1 == SERVER_URL then
                    ws = p2
                    connected = true
                    print("[GESTALT] Connected to brain!")

                    -- Register with the server
                    local regEvent = {
                        type = "register",
                        id = os.getComputerID(),
                        capabilities = currentCapabilities()
                    }
                    print("[GESTALT] Sending registration: " .. textutils.serialiseJSON(regEvent))
                    ws.send(textutils.serialiseJSON(regEvent))

                    keepaliveTimer = os.startTimer(KEEPALIVE_INTERVAL)
                end

            elseif event == "websocket_failure" then
                if p1 == SERVER_URL then
                    print("[ERROR] Connection failed: " .. tostring(p2))
                    break -- Retry connection
                end

            elseif event == "websocket_closed" then
                if p1 == SERVER_URL then
                    print("[GESTALT] Connection closed")
                    connected = false
                    keepaliveTimer = nil
                    break -- Retry connection
                end

            elseif event == "websocket_message" then
                if p1 == SERVER_URL then
                    local msg = p2
                    print("[GESTALT] Received message: " .. msg)

                    local ok, data = pcall(textutils.unserialiseJSON, msg)
                    if ok and data then
                        executeCommand(ws, data)
                    else
                        print("[ERROR] Failed to parse message: " .. tostring(data))
                    end
                end

            elseif event == "chat" then
                local username, message, uuid, isHidden = p1, p2, p3, p4
                if connected and not isHidden then
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
                    local regEvent = {
                        type = "register",
                        id = os.getComputerID(),
                        capabilities = currentCapabilities()
                    }
                    print("[GESTALT] Sending registration: " .. textutils.serialiseJSON(regEvent))
                    ws.send(textutils.serialiseJSON(regEvent))
                    keepaliveTimer = os.startTimer(KEEPALIVE_INTERVAL)
                end
            end
        end

        print("[GESTALT] Reconnecting in " .. RECONNECT_DELAY .. " seconds...")
        os.sleep(RECONNECT_DELAY)
    end
end

main()
