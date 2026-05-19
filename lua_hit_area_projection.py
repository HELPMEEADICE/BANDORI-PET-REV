from pathlib import Path
import sys

try:
    from lupa.luajit21 import LuaRuntime
except ModuleNotFoundError:
    from lupa.lua import LuaRuntime


_LUA = LuaRuntime(unpack_returned_tuples=True)

if _LUA.eval("jit == nil"):
    raise RuntimeError("LuaJIT is required for custom hit area handling")

_LUA_BASENAME = "custom_hit_area_state"


def _lua_source_path() -> Path:
    if getattr(sys, "frozen", False):
        frozen_dir = Path(sys.executable).resolve().parent
        bytecode_path = frozen_dir / f"{_LUA_BASENAME}.ljbc"
        if bytecode_path.exists():
            return bytecode_path
        return frozen_dir / f"{_LUA_BASENAME}.lua"
    return Path(__file__).resolve().with_name(f"{_LUA_BASENAME}.lua")


def _load_lua_chunk(path: Path):
    # Let Python open the file so frozen apps still work from non-ASCII paths on Windows.
    return _LUA.execute(path.read_bytes())


_NEW_CUSTOM_HIT_AREA_STATE = _load_lua_chunk(_lua_source_path())


class LuaCustomHitAreaState:
    def __init__(self):
        self._state = _NEW_CUSTOM_HIT_AREA_STATE()

    def clear(self):
        self._state.clear(self._state)

    def clear_projected(self):
        self._state.clear_projected(self._state)

    def set_scene_areas(self, scene_areas):
        self._state.set_scene_areas(
            self._state,
            _LUA.table_from(self._lua_scene_area(area) for area in scene_areas)
        )

    def _lua_scene_area(self, area):
        if len(area) == 5:
            name, min_x, max_x, min_y, max_y = area
            return _LUA.table_from((str(name), float(min_x), float(max_x), float(min_y), float(max_y)))
        min_x, max_x, min_y, max_y = area
        return _LUA.table_from(("", float(min_x), float(max_x), float(min_y), float(max_y)))

    def has_scene_areas(self) -> bool:
        return bool(self._state.has_scene_areas(self._state))

    def has_projected_areas(self) -> bool:
        return bool(self._state.has_projected_areas(self._state))

    def project(self, c0, c1, c2, width: float, height: float) -> bool:
        return bool(
            self._state.project(
                self._state,
                float(c0[0]),
                float(c0[1]),
                float(c1[0]),
                float(c1[1]),
                float(c2[0]),
                float(c2[1]),
                float(width),
                float(height),
            )
        )

    def hit_test(self, x: float, y: float) -> bool:
        return bool(self._state.hit_test(self._state, float(x), float(y)))

    def hit_test_name(self, x: float, y: float) -> str:
        name = self._state.hit_test_name(self._state, float(x), float(y))
        return "" if name is None else str(name)

    def bounds_for(self, name: str):
        bounds = self._state.bounds_for(self._state, str(name or ""))
        if bounds is None:
            return None
        min_x, max_x, min_y, max_y = bounds
        return float(min_x), float(max_x), float(min_y), float(max_y)

    def union_bounds(self):
        bounds = self._state.union_bounds(self._state)
        if bounds is None:
            return None
        min_x, max_x, min_y, max_y = bounds
        return float(min_x), float(max_x), float(min_y), float(max_y)
