--
-- Copyright (c) 2024 Kyle Evans <kevans@FreeBSD.org>
--
-- SPDX-License-Identifier: BSD-2-Clause
--

local core = require("orch.core")
local direct = require("orch.direct")
local scripter = require("orch.scripter")
local orch = {}

-- env: table of values that will be exposed to the orch script's environment.
-- A user of this library may add to the orch.env before calling
-- orch.run_script() and see their changes in the script's environment.
orch.env = scripter.env

-- run_script(scriptfile[, config]): run `scriptfile` as an .orch script, with
-- an optional configuration table that may be supplied.
--
-- The currently recognized configuration items are `alter_path` (boolean) that
-- indicates that the script's directory should be added to PATH, and `command`
-- (table) to indicate the argv of a process to spawn before running the script.
orch.run_script = scripter.run_script

-- sleep(duration): sleep for the given duration, in seconds.  Fractional
-- seconds are supported; core uses nanosleep(2) to implement sleep(), so this
-- is at least somewhat high resolution.
orch.sleep = core.sleep

-- spawn(cmd...): spawn the given command, returning a process that may be
-- manipulated as needed.
orch.spawn = direct.spawn

-- Reset all of the state; this largely means resetting the scripting bits, as
-- a user of this lib won't really need to reset anything.
function orch.reset()
	scripter.reset()
	assert(core.reset())
end

return orch
