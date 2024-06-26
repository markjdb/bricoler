-- Copyright (c) Mark Johnston <markj@FreeBSD.org>
--
-- SPDX-License-Identifier: BSD-2-Clause

-- Hand-rolled classes.  Define one with something like this:
--
--   local Foo = Class({<prototype fields>}, {<property fields>})
--
--   function Foo:_ctor(props)
--       -- "self" has properties assigned already.
--       ...
--       return self
--   end
--
--   function Foo:method()
--       ...
--   end
--
-- Where <property fields> is a table of property names and their types, e.g.,
--
--   {
--       foo = "string",
--       bar = "function",
--       baz = "*", -- Any value is OK.
--   }
--
-- Then create an instance with:
--
--   local foo = Foo{<properties>}
--
-- "foo" will be instantiated with a copy of the prototype and any
-- caller-supplied properties.  Foo's _ctor function, if defined,
-- is invoked after the properties are copied into the new object.
--
-- All properties and prototype fields are public.  Prefix them with an
-- underscore to indicate that they're private.

local function class(proto, props)
    local builtins = { "string", "number", "boolean", "table", "function", "*" }

    local function deepcopy(from, to)
        for k, v in pairs(from) do
            if type(v) == "table" then
                v = deepcopy(v, {})
            end
            to[k] = v
        end
        return to
    end

    -- Does the value "v" belong to the type "t"?
    local function valid(v, t)
        for _, candidate in ipairs(builtins) do
            if t == candidate then
                if t == "*" then
                    return true
                else
                    return type(v) == t
                end
            end
        end
        return false
    end

    -- A class is its own metatable.  This __index metamethod ensures that
    -- any defined property can be accessed even if it hasn't been set.
    local c = {}
    c.__index = function (t, key)
        local mt = getmetatable(t)
        if rawget(mt, key) then
            return mt[key]
        elseif mt._props[key] then
            return nil
        end
        error("Unknown class property '" .. key .. "'")
    end

    for k, v in pairs(props) do
        if type(v) == "string" then
            for _, candidate in ipairs(builtins) do
                if v == candidate then
                    break
                end
                if _ == #builtins then
                    error("Property '" .. k .. "' must have a type in " .. table.concat(builtins, ", "))
                end
            end
        elseif type(v) ~= "function" then
            error("Property '" .. k .. "' must be a string or a function")
        end
    end
    c._proto = proto
    c._props = props
    -- Let the consumer use the prototype fields as static class fields. 
    for k, v in pairs(proto) do
        c[k] = v
    end

    -- Provide a default constructor so that classes can override it.
    c._ctor = function()
    end

    -- Instantiate a new object when the class is called.  The prototype is
    -- copied into the new object and properties given to the constructor are
    -- checked and set.  Finally the object-specific constructor, if any, is
    -- called.
    c.__call = function(self, ...)
        local object = deepcopy(self._proto, {})
        if select("#", ...) ~= 1 then
            error("Constructors take a single table parameter")
        end
        local t = select(1, ...)
        if type(t) ~= "table" then
            error("Constructor parameter must be a table")
        end
        for k, v in pairs(t) do
            if self._props[k] then
                if type(self._props[k]) == "string" then
                    if not valid(v, self._props[k]) then
                        error("Property '" .. k .. "' must have type " .. self._props[k])
                    end
                elseif type(self._props[k]) == "function" then
                    if not self._props[k](v) then
                        error("Property '" .. k .. "' value '" .. v .. "' is invalid")
                    end
                else
                    error("Unknown property type '" .. type(self._props[k]) .. "'")
                end
                object[k] = v
            else
                error("Unknown class property '" .. k .. "'")
            end
        end
        object = setmetatable(object, self)
        object:_ctor(t)
        return object
    end
    return setmetatable(c, c)
end

return class
