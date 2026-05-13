return function()
    local state = {
        scene_areas = {},
        projected_areas = {},
    }

    function state:clear()
        self.scene_areas = {}
        self.projected_areas = {}
    end

    function state:clear_projected()
        self.projected_areas = {}
    end

    function state:set_scene_areas(scene_areas)
        self.scene_areas = scene_areas or {}
        self.projected_areas = {}
    end

    function state:has_scene_areas()
        return #self.scene_areas > 0
    end

    function state:has_projected_areas()
        return #self.projected_areas > 0
    end

    function state:project(c0x, c0y, c1x, c1y, c2x, c2y, width, height)
        local projected = {}
        self.projected_areas = projected

        local ax = c1x - c0x
        local ay = c1y - c0y
        local bx = c2x - c0x
        local by = c2y - c0y
        local det = ax * by - bx * ay
        if det == 0 then
            return false
        end

        local inv_det = 1.0 / det

        for i = 1, #self.scene_areas do
            local area = self.scene_areas[i]
            local name = area[1]
            local min_x = area[2]
            local max_x = area[3]
            local min_y = area[4]
            local max_y = area[5]

            local dx0 = min_x - c0x
            local dx1 = max_x - c0x
            local dy0 = min_y - c0y
            local dy1 = max_y - c0y

            local p0x = (by * dx0 - bx * dy0) * inv_det * width
            local p0y = (-ay * dx0 + ax * dy0) * inv_det * height
            local p1x = (by * dx0 - bx * dy1) * inv_det * width
            local p1y = (-ay * dx0 + ax * dy1) * inv_det * height
            local p2x = (by * dx1 - bx * dy0) * inv_det * width
            local p2y = (-ay * dx1 + ax * dy0) * inv_det * height
            local p3x = (by * dx1 - bx * dy1) * inv_det * width
            local p3y = (-ay * dx1 + ax * dy1) * inv_det * height

            projected[#projected + 1] = {
                name,
                math.min(p0x, p1x, p2x, p3x),
                math.max(p0x, p1x, p2x, p3x),
                math.min(p0y, p1y, p2y, p3y),
                math.max(p0y, p1y, p2y, p3y),
            }
        end

        return true
    end

    function state:hit_test_name(x, y)
        for i = 1, #self.projected_areas do
            local area = self.projected_areas[i]
            if area[2] <= x and x <= area[3] and area[4] <= y and y <= area[5] then
                return area[1]
            end
        end
        return nil
    end

    function state:hit_test(x, y)
        if self:hit_test_name(x, y) ~= nil then
            return true
        end
        return false
    end

    function state:bounds_for(name)
        name = tostring(name or "")
        for i = 1, #self.projected_areas do
            local area = self.projected_areas[i]
            if area[1] == name then
                return area[2], area[3], area[4], area[5]
            end
        end
        return nil
    end

    function state:union_bounds()
        if #self.projected_areas == 0 then
            return nil
        end
        local min_x = self.projected_areas[1][2]
        local max_x = self.projected_areas[1][3]
        local min_y = self.projected_areas[1][4]
        local max_y = self.projected_areas[1][5]
        for i = 2, #self.projected_areas do
            local area = self.projected_areas[i]
            min_x = math.min(min_x, area[2])
            max_x = math.max(max_x, area[3])
            min_y = math.min(min_y, area[4])
            max_y = math.max(max_y, area[5])
        end
        return min_x, max_x, min_y, max_y
    end

    return state
end
