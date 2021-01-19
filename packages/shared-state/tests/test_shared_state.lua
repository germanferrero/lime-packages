local utils = require 'lime.utils'
local test_utils = require 'tests.utils'
local SharedState = require 'shared-state'

local test_dir

describe('LiMe Utils tests #sharedstate', function()
    it('test load a new and empty db', function()
        local sharedState = SharedState('foo')
        sharedState.setDataDir(test_dir)
        local data = sharedState.get()
        assert.are.same({}, data)
    end)

    before_each('', function()
        test_dir = test_utils.setup_test_dir()
    end)

    after_each('', function()
        test_utils.teardown_test_dir()
    end)

end)
