local peripherals = require("blueking.peripherals")

local function execute(ws, command)
    print("[GESTALT] Executing command: " .. command.name .. " (id: " .. command.id .. ")")

    local errorMsg

    if command.name == "message" then
        local ok, result = pcall(function()
            return peripherals.sendMessage(command.args.message)
        end)

        if ok and result then
            errorMsg = nil
        elseif ok then
            errorMsg = "Failed to send message (no chatBox)"
        else
            errorMsg = tostring(result)
        end
    else
        errorMsg = "Unknown command: " .. command.name
    end

    local resultEvent = {
        type = "command_result",
        command_id = command.id,
        error = errorMsg
    }

    local resultJson = textutils.serialiseJSON(resultEvent)
    print("[GESTALT] Sending command result: " .. resultJson)
    ws.send(resultJson)
end

return { execute = execute }
