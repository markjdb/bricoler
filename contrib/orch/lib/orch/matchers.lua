--
-- Copyright (c) 2024 Kyle Evans <kevans@FreeBSD.org>
--
-- SPDX-License-Identifier: BSD-2-Clause
--

local core = require('orch.core')
local matchers = {}

local PatternMatcher = {}
function PatternMatcher:new()
	local obj = setmetatable({}, self)
	self.__index = self
	return obj
end
function PatternMatcher.match()
	-- All matchers should return start, last of match
	return false
end

local LuaMatcher = PatternMatcher:new()
function LuaMatcher.match(pattern, buffer)
	return buffer:find(pattern)
end

local PlainMatcher = PatternMatcher:new()
function PlainMatcher.match(pattern, buffer)
	return buffer:find(pattern, nil, true)
end

local PosixMatcher = PatternMatcher:new()
function PosixMatcher.compile(pattern)
	return assert(core.regcomp(pattern))
end
function PosixMatcher.match(pattern, buffer)
	return pattern:find(buffer)
end

-- Exported: the base for making new matchers, as well as a table of available
-- matchers.
matchers.PatternMatcher = PatternMatcher

-- default will be configurable via `matcher()`
matchers.available = {
	default = LuaMatcher,
	lua = LuaMatcher,
	plain = PlainMatcher,
	posix = PosixMatcher,
}

return matchers
