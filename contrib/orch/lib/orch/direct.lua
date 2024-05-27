--
-- Copyright (c) 2024 Kyle Evans <kevans@FreeBSD.org>
--
-- SPDX-License-Identifier: BSD-2-Clause
--

local actions = require('orch.actions')
local context = require('orch.context')
local matchers = require('orch.matchers')
local process = require('orch.process')

local direct = {}

direct.defaults = {
	timeout = 10,
}

local direct_ctx = context:new()
function direct_ctx.execute(_, callback)
	callback()
end
function direct_ctx:fail(_, contents)
	if self.fail_handler then
		self.fail_handler(contents)
	end
	return false
end

-- Wraps a process, provide everything we offer in actions.defined as a wrapper
local DirectProcess = {}
function DirectProcess:new(cmd, ctx)
	local pwrap = setmetatable({}, self)
	self.__index = self

	pwrap._process = process:new(cmd, ctx)
	pwrap.ctx = ctx
	pwrap.timeout = direct.defaults.timeout

	ctx.process = pwrap._process

	return pwrap
end
function DirectProcess:match(pattern, matcher)
	matcher = matcher or matchers.available.default

	local action = actions.MatchAction:new("match")
	action.timeout = self.timeout
	action.pattern = pattern
	action.matcher = matcher

	if matcher.compile then
		action.pattern_obj = action.matcher.compile(pattern)
	end

	return self._process:match(action)
end
for name, def in pairs(actions.defined) do
	-- Each of these gets a function that generates the action and then
	-- subsequently executes it.
	DirectProcess[name] = function(pwrap, ...)
		local action = actions.MatchAction:new(name, def.execute)
		local args = { ... }

		action.ctx = pwrap.ctx

		if def.init then
			def.init(action, args)
		end

		return action:execute()
	end
end

function direct.spawn(...)
	local fresh_ctx = {}

	for k, v in pairs(direct_ctx) do
		fresh_ctx[k] = v
	end

	return DirectProcess:new({...}, fresh_ctx)
end

return direct
