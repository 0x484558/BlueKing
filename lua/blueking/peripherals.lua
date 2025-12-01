local config = require("blueking.config")

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
        chatBox.sendMessage(message, config.bot_name)
        return true
    else
        print("[ERROR] No chatBox found")
        return false
    end
end

return {
    refreshChatBox = refreshChatBox,
    currentCapabilities = currentCapabilities,
    sendMessage = sendMessage
}
