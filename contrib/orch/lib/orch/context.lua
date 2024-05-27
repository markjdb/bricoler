--
-- Copyright (c) 2024 Kyle Evans <kevans@FreeBSD.org>
--
-- SPDX-License-Identifier: BSD-2-Clause
--

local Context = {}
function Context:new(def)
	local ctx = setmetatable(def or {}, self)
	self.__index = self

	return ctx
end
function Context.execute(_)
	return true
end
function Context.fail(_)
	return false
end

return Context
