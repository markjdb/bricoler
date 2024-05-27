--
-- Copyright (c) 2024 Kyle Evans <kevans@FreeBSD.org>
--
-- SPDX-License-Identifier: BSD-2-Clause
--

local core = require("orch.core")

local context = require("orch.context")
local actions = require("orch.actions")
local matchers = require("orch.matchers")
local process = require("orch.process")
local tty = core.tty
local scripter = {env = {}}

local CTX_QUEUE = 1
local CTX_FAIL = 2
local CTX_CALLBACK = 3

local current_ctx

local match_valid_cfg = {
	callback = true,
	timeout = true,
}

-- Sometimes a queue, sometimes a stack.  Oh well.
local Queue = {}
function Queue:push(item)
	self.elements[#self.elements + 1] = item
end
function Queue:back()
	return self.elements[#self.elements]
end
function Queue:clear()
	self.elements = {}
end
function Queue:remove(elem)
	for k, v in ipairs(self.elements) do
		if v == elem then
			for nk = k + 1, #self.elements do
				self.elements[nk - 1] = self.elements[nk]
			end

			self.elements[#self.elements] = nil

			return true
		end
	end
end
function Queue:pop()
	local item = self.elements[#self.elements]
	self.elements[#self.elements] = nil
	return item
end
function Queue:count()
	return #self.elements
end
function Queue:empty()
	return #self.elements == 0
end
function Queue:each(cb)
	for _, v in ipairs(self.elements) do
		cb(v)
	end
end
function Queue:items()
	return self.elements
end

local MatchContext = setmetatable({}, { __index = Queue })
function MatchContext:new()
	local obj = setmetatable({}, self)
	self.__index = self
	obj.elements = {}
	obj.last_processed = 0
	obj.errors = false
	return obj
end
function MatchContext:dump(level)
	level = level or 1
	self:each(function(action)
		action:dump(level)
	end)
end
function MatchContext:error()
	return self.errors
end
function MatchContext:process()
	local latest = self.last_processed
	local ctx_actions = self:items()

	for idx, action in ipairs(ctx_actions) do
		if idx <= latest then
			goto skip
		end

		self.last_processed = idx
		if action.type == "match" then
			local ctx_cnt = current_ctx.match_ctx_stack:count()
			local current_process = current_ctx.process

			if not current_process then
				error("Script did not spawn process prior to matching")
			end

			-- Another action in this context could have swapped out the process
			-- from underneath us, so pull the buffer at the last possible
			-- minute.
			if not current_process:match(action) then
				self.errors = true
				return false
			end

			-- Even if this is the last element, doesn't matter; we're finished
			-- here.
			if current_ctx.match_ctx_stack:count() ~= ctx_cnt then
				break
			end
		elseif not action:execute() then
			return false
		end

		::skip::
	end

	return self.last_processed == #ctx_actions
end
function MatchContext:process_one()
	local ctx_actions = self:items()
	local elapsed = 0
	local current_process = current_ctx.process

	if not current_process then
		error("Script did not spawn process prior to matching")
	end

	-- Return low, high timeout of current batch
	local function get_timeout()
		local low

		for _, action in ipairs(ctx_actions) do
			if action.timeout <= elapsed then
				goto skip
			end
			if low == nil then
				low = action.timeout
				goto skip
			end

			low = math.min(low, action.timeout)

			::skip::
		end
		return low
	end

	-- The process can't be swapped out by an immediate descendant of a one()
	-- block, but it could be swapped out by a later block.  We don't care,
	-- though, because we won't need the buffer anymore.
	local buffer = current_process.buffer

	local start = core.time()
	local matched

	local function match_any()
		local elapsed_now = core.time() - start
		for _, action in ipairs(ctx_actions) do
			if action.timeout >= elapsed_now and buffer:_matches(action) then
				matched = true
				return true
			end
		end

		return false
	end

	local tlo

	while not matched and not buffer.eof do
		-- We recalculate every iteration to rule out any actions that have
		-- timed out.  Anything with a timeout lower than our current will be
		-- ignored for matching.
		elapsed = core.time() - start
		tlo = get_timeout()

		if tlo == nil then
			break
		end

		assert(tlo > elapsed)
		buffer:refill(match_any, tlo - elapsed)
	end

	if not matched then
		if not current_ctx:fail(self.action, buffer:contents()) then
			self.errors = true
			return false
		end
	end

	return true
end

local script_ctx = context:new({
	match_ctx_stack = setmetatable({ elements = {} }, { __index = Queue }),
})

function script_ctx.match_ctx_stack:dump()
	self:each(function(dctx)
		dctx:dump()
	end)
end
-- Execute a chunk; may either be a callback from a match block, or it may be
-- an entire included file.  Either way, each execution gets a new match context
-- that we may or may not use.  We'll act upon the latest in the stack no matter
-- what happens.
function script_ctx:execute(func, match_ctx)
	local match_ctx_stack = self.match_ctx_stack
	local prev_ctx = self.match_ctx
	self.match_ctx = match_ctx or MatchContext:new()

	assert(pcall(func))

	-- If we created a new context for this, we may need to put it on the
	-- stack.  We'll leave caller-supplied contexts alone.
	if not match_ctx then
		if not self.match_ctx:empty() then
			-- If it defined any queued items, we'll leave it as the
			-- currently open match ctx.
			match_ctx_stack:push(self.match_ctx)
		else
			self.match_ctx = match_ctx_stack:back()
		end
	else
		self.match_ctx = prev_ctx
	end
end

function script_ctx:fail(action, buffer)
	if self.fail_callback then
		local restore_ctx = self:state(CTX_FAIL)
		self.fail_callback(buffer)
		self:state(restore_ctx)

		return true
	else
		-- Print diagnostics if we can
		if action.print_diagnostics then
			action:print_diagnostics()
		end
	end

	return false
end
function script_ctx:reset()
	if self.process then
		assert(self.process:close())
	end

	self.process = nil

	self.match_ctx_stack:clear()
	self.match_ctx = nil
	self._state = CTX_QUEUE
	self.timeout = actions.default_timeout
end
function script_ctx:state(new_state)
	local prev_state = self._state
	self._state = new_state or prev_state
	return prev_state
end

local function include_file(ctx, file, alter_path, env)
	local f = assert(core.open(file, alter_path))
	local chunk = f:read("l")

	if not chunk then
		error(file .. " appears to be empty!")
	end

	if chunk:match("^#!") then
		chunk = ""
	else
		-- line-based read will strip the newline
		chunk = chunk .. "\n"
	end

	chunk = chunk .. assert(f:read("a"))
	local func = assert(load(chunk, "@" .. file, "t", env))

	return ctx:execute(func)
end

local function grab_caller(level)
	local info = debug.getinfo(level + 1, "Sl")

	return info.short_src, info.currentline
end

-- Bits available to the sandbox; scripter.env functions are directly exposed,
-- and may be added to via orch.env.
function scripter.env.hexdump(str)
	if current_ctx:state() == CTX_QUEUE then
		error("hexdump may only be called in a non-queue context")
	end

	local output = ""

	local function append(left, right)
		if output ~= "" then
			output = output .. "\n"
		end

		left = string.format("%-50s", left)
		output = output .. "DEBUG: " .. left .. "\t|" .. right .. "|"
	end

	local lcol, rcol = "", ""
	for c = 1, #str do
		if (c - 1) % 16 == 0 then
			-- Flush output every 16th character
			if c ~= 1 then
				append(lcol, rcol)
				lcol = ""
				rcol = ""
			end
		else
			if (c - 1) % 8 == 0 then
				lcol = lcol .. "  "
			else
				lcol = lcol .. " "
			end
		end

		local ch = str:sub(c, c)
		local byte = string.byte(ch)
		lcol = lcol .. string.format("%.02x", byte)
		if byte >= 0x20 and byte < 0x7f then
			rcol = rcol .. ch
		else
			rcol = rcol .. "."
		end
	end

	if lcol ~= "" then
		append(lcol, rcol)
	end

	io.stderr:write(output .. "\n")
	return true
end

function scripter.env.matcher(val)
	local matcher_obj

	for k, v in pairs(matchers.available) do
		if k == val then
			matcher_obj = v
			break
		end
	end

	if not matcher_obj then
		error("Unknown matcher '" .. val .. "'")
	end

	actions.default_matcher = matcher_obj

	return true
end

function scripter.env.timeout(val)
	if val == nil or val < 0 then
		error("Timeout must be >= 0")
	end
	current_ctx.timeout = val
end

local extra_actions = {
	debug = {
		allow_direct = true,
		init = function(action, args)
			action.message = args[1]
		end,
		execute = function(action)
			io.stderr:write("DEBUG: " .. action.message .. "\n")
			return true
		end,
	},
	enqueue = {
		allow_direct = true,
		init = function(action, args)
			action.callback = args[1]
		end,
		execute = function(action)
			local ctx = action.ctx
			local restore_ctx = ctx:state(CTX_CALLBACK)

			ctx:execute(action.callback)

			ctx:state(restore_ctx)
			return true
		end,
	},
	exit = {
		allow_direct = true,
		init = function(action, args)
			action.code = args[1]
		end,
		execute = function(action)
			os.exit(action.code)
		end,
	},
	fail = {
		init = function(action, args)
			action.callback = args[1]
		end,
		execute = function(action)
			action.ctx.fail_callback = action.callback
			return true
		end,
	},
	match = {
		print_diagnostics = function(action)
			io.stderr:write(string.format("[%s]:%d: match (pattern '%s') failed\n",
			    action.src, action.line, action.pattern))
		end,
		init = function(action, args)
			local pattern = args[1]

			action.pattern = pattern
			action.timeout = action.ctx.timeout

			if action.matcher.compile then
				action.pattern_obj = action.matcher.compile(pattern)
			end

			local function set_cfg(cfg)
				for k, v in pairs(cfg) do
					if not match_valid_cfg[k] then
						error(k .. " is not a valid cfg field")
					end

					action[k] = v
				end
			end

			return set_cfg
		end,
	},
	one = {
		-- This does its own queue management
		auto_queue = false,
		init = function(action, args)
			local func = args[1]
			local parent_ctx = action.ctx.match_ctx

			parent_ctx:push(action)

			action.match_ctx = MatchContext:new()
			action.match_ctx.process = action.match_ctx.process_one
			action.match_ctx.action = action

			-- Now execute it
			script_ctx:execute(func, action.match_ctx)

			-- Sanity check the script
			for _, chaction in ipairs(action.match_ctx:items()) do
				if chaction.type ~= "match" then
					error("Type '" .. chaction.type .. "' not legal in a one() block")
				end
			end
		end,
		execute = function(action)
			action.ctx.match_ctx_stack:push(action.match_ctx)
			return false
		end,
	},
	sleep = {
		allow_direct = true,
		init = function(action, args)
			action.duration = args[1]
		end,
		execute = function(action)
			assert(core.sleep(action.duration))
			return true
		end,
	},
}

-- Valid config options:
--   * alter_path: boolean, add script's directory to $PATH (default: false)
--   * command: argv table to pass to spawn
function scripter.run_script(scriptfile, config)
	local done

	script_ctx:reset()
	current_ctx = script_ctx

	-- Make a copy of scripter.env at the time of script execution.  The
	-- environment is effectively immutable from the driver's perspective
	-- after execution starts, and we want to avoid a script from corrupting
	-- future executions when we eventually support that.
	local current_env = {}
	for k, v in pairs(scripter.env) do
		current_env[k] = v
	end

	local function generate_handler(name, def)
		return function(...)
			local action = actions.MatchAction:new(name, def.execute)
			local args = { ... }
			local ret, state

			action.ctx = current_ctx
			action.src, action.line = grab_caller(2)

			action.print_diagnostics = def.print_diagnostics

			if def.init then
				-- We preserve the return value of init() in case
				-- the action wanted to, e.g., return a callback
				-- for some good old fashion chaining like with
				-- match "foo" { config }.
				ret = def.init(action, args)
			end

			state = current_ctx:state()
			if state ~= CTX_QUEUE then
				if not def.allow_direct then
					error(name .. " may not be called in a direct context")
				end

				return action:execute()
			end

			-- Defaults to true if unset.
			local auto_queue = def.auto_queue
			if auto_queue == nil then
				auto_queue = true
			end

			if auto_queue then
				current_ctx.match_ctx:push(action)
			end
			return ret or true
		end
	end
	for name, def in pairs(actions.defined) do
		current_env[name] = generate_handler(name, def)
	end
	for name, def in pairs(extra_actions) do
		current_env[name] = generate_handler(name, def)
	end

	-- Note that the orch(1) driver will setup alter_path == true; scripts
	-- importing orch.lua are expected to be more explicit.
	include_file(script_ctx, scriptfile, config and config.alter_path, current_env)
	--current_ctx.match_ctx_stack:dump()

	if config and config.command then
		current_ctx.process = process:new(config.command, current_ctx)
	end

	if current_ctx.match_ctx_stack:empty() then
		error("script did not define any actions")
	end

	-- To run the script, we'll grab the back of the context stack and process
	-- that.
	while not done do
		local run_ctx = current_ctx.match_ctx_stack:back()

		if run_ctx:process() then
			current_ctx.match_ctx_stack:remove(run_ctx)
			done = current_ctx.match_ctx_stack:empty()
		elseif run_ctx:error() then
			return false
		end
	end

	return true
end

-- Inherited from our environment
scripter.env.assert = assert
scripter.env.string = string
scripter.env.table = table
scripter.env.tty = tty
scripter.env.type = type

function scripter.reset()
	script_ctx:reset()
end

return scripter
