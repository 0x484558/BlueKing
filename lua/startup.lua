-- startup.lua (optional)
-- Auto-start the LLM chat bridge on computer boot

-- Configuration
local PROGRAM_PATH = "blueking.lua"
local AUTO_RESTART = true
local RESTART_DELAY = 3  -- seconds

-- Clear screen
term.clear()
term.setCursorPos(1, 1)
-- Check if program exists
if not fs.exists(PROGRAM_PATH) then
    print("Error: " .. PROGRAM_PATH .. " not found!")
    print("Please ensure llm_chat.lua is in the root directory.")
    return
end

-- Run the program with auto-restart
while true do
    print(PROGRAM_PATH)

    -- Run the program
    shell.run(PROGRAM_PATH)

    print()
    print("Program stopped!")

    if not AUTO_RESTART then
        print("Auto-restart is disabled.")
        break
    end

    print("Restarting in " .. RESTART_DELAY .. " seconds...")
    print("Press Ctrl+T to cancel restart.")

    -- Wait with ability to cancel
    local timer_id = os.startTimer(RESTART_DELAY)

    while true do
        local event, param = os.pullEvent()

        if event == "timer" and param == timer_id then
            break
        elseif event == "terminate" then
            print()
            print("Restart cancelled.")
            return
        end
    end

    print()
    print("Restarting...")
    print()
end
