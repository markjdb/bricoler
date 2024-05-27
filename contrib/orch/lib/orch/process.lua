--
-- Copyright (c) 2024 Kyle Evans <kevans@FreeBSD.org>
--
-- SPDX-License-Identifier: BSD-2-Clause
--

local core = require("orch.core")
local tty = core.tty

local MatchBuffer = {}
function MatchBuffer:new(process, ctx)
	local obj = setmetatable({}, self)
	self.__index = self
	self.buffer = ""
	self.ctx = ctx
	self.process = process
	self.eof = false
	return obj
end
function MatchBuffer:_matches(action)
	local first, last = action:matches(self.buffer)

	if not first then
		return false
	end

	-- On match, we need to trim the buffer and signal completion.
	action.completed = true
	self.buffer = self.buffer:sub(last + 1)

	-- Return value is not significant, ignored.
	if action.callback then
		self.ctx:execute(action.callback)
	end

	return true
end
function MatchBuffer:contents()
	return self.buffer
end
function MatchBuffer:empty()
	return #self.buffer == 0
end
function MatchBuffer:refill(action, timeout)
	assert(not self.eof)

	if not self.process:released() then
		self.process:release()
	end
	local function refill(input)
		if not input then
			self.eof = true
			return true
		end

		if self.process.log then
			self.process.log:write(input)
		end

		self.buffer = self.buffer .. input
		if type(action) == "table" then
			return self:_matches(action)
		else
			assert(type(action) == "function")

			return action()
		end
	end

	if timeout then
		assert(self.process:read(refill, timeout))
	else
		assert(self.process:read(refill))
	end
end
function MatchBuffer:match(action)
	if not self:_matches(action) and not self.eof then
		self:refill(action, action.timeout)
	end

	return action.completed
end

-- Wrap a process and perform operations on it.
local Process = {}
function Process:new(cmd, ctx)
	local pwrap = setmetatable({}, self)
	self.__index = self

	pwrap._process = assert(core.spawn(table.unpack(cmd)))
	pwrap.buffer = MatchBuffer:new(pwrap, ctx)
	pwrap.cfg = {}
	pwrap.ctx = ctx
	pwrap.is_raw = false

	pwrap.term = assert(pwrap._process:term())
	local mask = pwrap.term:fetch("lflag")

	mask = mask & ~tty.lflag.ECHO
	assert(pwrap.term:update({
		lflag = mask,
	}))

	return pwrap
end
-- Proxied through to the wrapped process
function Process:released()
	return self._process:released()
end
function Process:release()
	return self._process:release()
end
function Process:read(func, timeout)
	if timeout then
		return self._process:read(func, timeout)
	else
		return self._process:read(func)
	end
end
function Process:raw(is_raw)
	local prev_raw = self.is_raw
	self.is_raw = is_raw
	return prev_raw
end
function Process:write(data, cfg)
	if not self.is_raw then
		-- Convert ^[A-Z] -> cntrl sequence
		local quoted = false
		for i = 1, #data do
			if i > #data then
				break
			end

			local ch = data:sub(i, i)

			if quoted then
				quoted = false
			elseif ch == "\\" then
				quoted = true
				data = data:sub(1, i - 1) .. data:sub(i + 1)
			elseif ch == "^" then
				if i == #data then
					error("Incomplete CNTRL character at end of buffer")
				end

				local esch = data:sub(i + 1, i + 1)
				local esc = string.byte(esch)
				if esc < 0x40 or esc > 0x5f then
					error("Invalid escape of '" .. esch .. "'")
				end

				esch = string.char(esc - 0x40)
				data = data:sub(1, i - 1) .. esch .. data:sub(i + 2)
			end
		end
	end
	if self.log then
		self.log:write(data)
	end

	local bytes, delay
	local function set_rate(which_cfg)
		if not which_cfg or not which_cfg.rate then
			return
		end

		local rate = which_cfg.rate

		if rate.bytes ~= nil then
			bytes = rate.bytes
		end
		if rate.delay ~= nil then
			delay = rate.delay
		end
	end

	-- Give process configuration a first go at it
	set_rate(self.cfg)
	set_rate(cfg)

	-- If we didn't have a configured rate, just send a single batch of all
	-- data without delay.
	if not bytes or bytes == 0 then
		bytes = #data
		delay = nil
	end

	local sent = 0
	local total = #data

	while sent < total do
		local bound = math.min(total, sent + bytes)

		assert(self._process:write(data:sub(sent + 1, bound)))
		sent = bound

		if delay and sent < total then
			core.sleep(delay)
		end
	end

	return sent
end
function Process:close()
	assert(self._process:close())

	-- Flush output, close everything out
	self:logfile(nil)
	self._process = nil
	self.term = nil
	return true
end
-- Our own special salt
function Process:logfile(file)
	if self.log then
		self.log:flush()
		self.log:close()
	end

	self.log = file
end
function Process:match(action)
	local buffer = self.buffer
	if not buffer:match(action) then
		if not self.ctx:fail(action, buffer:contents()) then
			return false
		end
	end

	return true
end
function Process:set(cfg)
	for k, v in pairs(cfg) do
		self.cfg[k] = v
	end
end

return Process
