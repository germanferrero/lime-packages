#!/usr/bin/lua

--! Minimalistic CRDT-like shared state structure suitable for mesh networks
--!
--! Copyright (C) 2019-2020  Gioacchino Mazzurco <gio@altermundi.net>
--!
--! This program is free software: you can redistribute it and/or modify
--! it under the terms of the GNU Affero General Public License version 3 as
--! published by the Free Software Foundation.
--!
--! This program is distributed in the hope that it will be useful,
--! but WITHOUT ANY WARRANTY; without even the implied warranty of
--! MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
--! GNU Affero General Public License for more details.
--!
--! You should have received a copy of the GNU Affero General Public License
--! along with this program.  If not, see <http://www.gnu.org/licenses/>.

local fs = require("nixio.fs")
local JSON = require("luci.jsonc")
local nixio = require("nixio")
local uci = require("uci")

local function SharedState(dataType, pLogger)
	--! Name of the CRDT is mandatory
	if type(dataType) ~= "string" or dataType:len() < 1 then return nil end

	--! Map<Key, {bleachTTL, author, data}>
	--!   bleachTTL is the count of how much bleaching should occur before the
	--!     entry expires
	--!   author is the name of the host who generated that entry
	--!   data is the value of the entry
	local self_storage = {}

	--! File descriptor of the persistent file storage
	local self_storageFD = nil

	--! true if self_storage has changed after loading
	local self_changed = false

	local self_dataDir
	local self_dataFile
	local self_hooksDir = "/etc/shared-state/hooks/"..dataType.."/"

	--! true when persistent storage file is locked by this instance
	local self_locked = false


	local self_log = function (level, message)
	end
	if type(pLogger) == "function" then self_log = pLogger end

	local sharedState = {}

    function sharedState.setDataDir(dir)
        self_dataDir = dir
        self_dataFile = dir..dataType..".json"
    end

    sharedState.setDataDir("/var/shared-state/data/")

	--! Returns true if at least one entry expired, false otherwise
	function sharedState._bleach()
		local substancialChange = false
		for k,v in pairs(self_storage) do
			if(v.bleachTTL < 2) then
				self_storage[k] = nil
				substancialChange = true
			else
				v.bleachTTL = v.bleachTTL-1
			end
			self_changed = true
		end
		return substancialChange
	end

	function sharedState.bleach()
		sharedState.lock()
		sharedState.load()
		local shouldNotify = sharedState._bleach()
		sharedState.save()
		sharedState.unlock()
		--! Avoid hooks being called if data hasn't substantially changed
		if(shouldNotify) then sharedState.notifyHooks() end
	end

	function sharedState._insert(key, data, bleachTTL)
		bleachTTL = bleachTTL or 30
		self_storage[key] = {
			bleachTTL=bleachTTL,
			author=io.input("/proc/sys/kernel/hostname"):read("*line"),
			data=data
		}
		self_changed = true
	end

	function sharedState.insert(data)
		sharedState.lock()
		sharedState.load()
		for key, lv in pairs(data) do sharedState._insert(key, lv) end
		sharedState.save()
		sharedState.unlock()
		sharedState.notifyHooks()
	end

	function sharedState.load()
		sharedState._merge(JSON.parse(self_storageFD:readall()), false)
	end

	function sharedState.lock(maxwait)
		if self_locked then return end
		maxwait = maxwait or 10

		fs.mkdirr(self_dataDir)
		self_storageFD = nixio.open(
			self_dataFile, nixio.open_flags("rdwr", "creat") )

		for i=1,maxwait do
			if not self_storageFD:lock("tlock") then
				nixio.nanosleep(1)
			else
				self_locked = true
				break
			end
		end

		if not self_locked then
			self_log( "err",
			          arg[0], arg[1], arg[2], "Failed acquiring lock on data!" )
			os.exit(-165)
		end
	end

	function sharedState._merge(stateSlice, notifyInsert)
		local stateSlice = stateSlice or {}
		if(notifyInsert == nil) then notifyInsert = true end

		for key,rv in pairs(stateSlice) do
			if rv.bleachTTL <= 0 then
				self_log( "debug", "sharedState.merge got expired entry" )
				self_changed = true
			else
				local lv = self_storage[key]
				if( lv == nil ) then
					self_storage[key] = rv
					self_changed = self_changed or notifyInsert
				elseif ( lv.bleachTTL < rv.bleachTTL ) then
					self_log( "debug", "Updating entry for: "..key.." older: "..
					          lv.bleachTTL.." newer: "..rv.bleachTTL )
					self_storage[key] = rv
					self_changed = self_changed or notifyInsert
				end
			end
		end
	end

	function sharedState.merge(stateSlice, notifyInsert)
		sharedState.lock()
		sharedState.load()
		sharedState._merge(stateSlice, notifyInsert)
		sharedState.save()
		sharedState.unlock()
		sharedState.notifyHooks()
	end

	function sharedState.notifyHooks()
		if self_changed then
			local jsonString = sharedState.toJsonString()
			if not fs.dir(self_hooksDir) then return end
			for hook in fs.dir(self_hooksDir) do
				local cStdin = io.popen(self_hooksDir.."/"..hook, "w")
				cStdin:write(jsonString)
				cStdin:close()
			end
		end
	end

	function sharedState._remove(key)
		if(self_storage[key] ~= nil and self_storage[key].data ~= nil)
		then sharedState.insert(key, nil) end
	end

	function sharedState.remove(keys)
		sharedState.lock()
		sharedState.load()
		for _,key in ipairs(keys) do sharedState._remove(key) end
		sharedState.save()
		sharedState.unlock()
		sharedState.notifyHooks()
	end

	function sharedState.save()
		if self_changed then
			local outFd = io.open(self_dataFile, "w")
			outFd:write(sharedState.toJsonString())
			outFd:close()
			outFd = nil
		end
	end

	function sharedState.httpRequest(url, body)
		local tmpfname = os.tmpname()

		local tmpfd = io.open(tmpfname, "w")
		tmpfd:write(body)
		tmpfd:close()
		tmpfd = nil

		local cmd = "uclient-fetch --no-check-certificate -q -O- --timeout=3 "
		cmd = cmd.."--post-file='"..tmpfname.."' '"..url.."' ; "
		cmd = cmd.."rm -f '"..tmpfname.."'"
		local fd = io.popen(cmd)

		local value = fd:read("*a")
		fd:close()

		return value
	end

	function sharedState._sync(urls)
		urls = urls or {}

		if #urls < 1 then
			local uci_cursor = uci:cursor()
			local fixed_candidates =
					uci_cursor:get("shared-state", "options","candidates") or {}
			for _, line in pairs(fixed_candidates) do
				table.insert(
					urls,
					line.."/"..dataType )
			end

			io.input(io.popen(arg[0].."-get_candidates_neigh"))
			for line in io.lines() do
				table.insert(
					urls,
					"http://["..line.."]/cgi-bin/shared-state/"..dataType )
			end
		end

		for _,url in ipairs(urls) do
			local body = sharedState.toJsonString()

			local response = sharedState.httpRequest(url, body)

			if type(response) == "string" and response:len() > 1  then
				local parsedJson = JSON.parse(response)
				if parsedJson then sharedState.merge(parsedJson) end
			else
				self_log( "debug", "error requesting "..url )
			end
		end
	end

	function sharedState.sync(urls)
		sharedState.lock()
		sharedState.load()
		sharedState.unlock()
		sharedState._sync(urls)
		sharedState.lock()
		sharedState.load() -- Take in account changes happened during sync
		sharedState.save()
		sharedState.unlock()
		sharedState.notifyHooks()
	end

	function sharedState.toJsonString()
		return JSON.stringify(self_storage)
	end

	function sharedState.get()
		sharedState.lock()
		sharedState.load()
		sharedState.unlock()
		return self_storage
	end

	function sharedState.unlock()
		if not self_locked then return end
		self_storageFD:lock("ulock")
		self_storageFD:close()
		self_storageFD = nil
		self_locked = false
	end

	return sharedState
end

return SharedState
