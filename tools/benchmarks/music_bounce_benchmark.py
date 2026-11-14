"""Measure real old/new Music Bounce work on one machine, without a pet GPU.

Build the native binary + music_benchmark example and the Python IPC extension.
The old modules are loaded from the audited Git commit, never from production.
Old: actual Qt 30 ms tick, Python Core Audio worker, springs, JSON and mapped IPC.
New: actual NativeMusicService plus N independent headless native frame consumers.
GPU/model/window cost is excluded in BOTH cases. RSS reports are not a full-app
memory comparison. --profile selects matching debug or release artifacts.
"""
import argparse
import ast
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import types
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
BASELINE = "a20bf47ac074e7f0b9c77f33e6370753a26fdbc9"
_cycle_kernel = None


def cpu_cycles(pid=None):
    """High-resolution Windows CPU accounting when GetProcessTimes rounds to zero.

    Cycles are reported as cycles, never converted to seconds using a guessed GHz.
    This benchmark-only ctypes code queries process accounting, not audio.
    """
    import ctypes
    global _cycle_kernel
    if _cycle_kernel is None:
        _cycle_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        _cycle_kernel.QueryProcessCycleTime.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulonglong)]
        _cycle_kernel.QueryProcessCycleTime.restype = ctypes.c_int
        _cycle_kernel.OpenProcess.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_uint]
        _cycle_kernel.OpenProcess.restype = ctypes.c_void_p
        _cycle_kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        _cycle_kernel.CloseHandle.restype = ctypes.c_int
    handle = _cycle_kernel.OpenProcess(0x1000, False, pid) if pid else ctypes.c_void_p(-1)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        cycles = ctypes.c_ulonglong()
        if not _cycle_kernel.QueryProcessCycleTime(handle, ctypes.byref(cycles)):
            raise ctypes.WinError(ctypes.get_last_error())
        return cycles.value
    finally:
        if pid:
            _cycle_kernel.CloseHandle(handle)


def legacy():
    def source(path):
        return subprocess.check_output(["git", "show", f"{BASELINE}:{path}"], cwd=ROOT).decode("utf-8")
    module = types.ModuleType("music_benchmark_baseline")
    sys.modules[module.__name__] = module
    exec(compile(source("bandori_audio/music_bounce.py"), "<frozen music baseline>", "exec"), module.__dict__)
    tree = ast.parse(source("bandori_ui/native_pet_services.py"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "NativePetServices")
    tick = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_music_tick")
    # Only redirect the import; preserve the actual production method's body.
    tick.body[0].module = module.__name__
    namespace = {"time": time}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[tick], type_ignores=[])), "<frozen service baseline>", "exec"), namespace)
    return module, namespace["_music_tick"]


def wait_qt(seconds):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(round(seconds * 1000), loop.quit)
    loop.exec()


def old_run(count, seconds, enabled):
    import psutil
    from PySide6.QtCore import QTimer
    from bandori_core.shared_memory_ipc import SharedMemoryLineQueue, encode_ipc_envelope
    module, tick = legacy()
    timings = []
    original = module._WindowsOutputMeter.read
    def timed_read(meter):
        start = time.perf_counter_ns()
        try:
            return original(meter)
        finally:
            timings.append(time.perf_counter_ns() - start)
    module._WindowsOutputMeter.read = timed_read
    queue = SharedMemoryLineQueue.create("music-benchmark-" + uuid.uuid4().hex)
    messages = [0]
    def control(char, command, **data):
        data.update(character=char, command=command)
        line = "NATIVE_CONTROL\t" + json.dumps(data, ensure_ascii=False)
        assert queue.publish(encode_ipc_envelope("benchmark", line))
        messages[0] += 1
    service = types.SimpleNamespace(cfg={"music_bounce_enabled": enabled}, roles=list(map(str, range(count))),
        _meter=None, _springs={}, _last_music=time.monotonic(), control=control)
    timer = QTimer()
    timer.setInterval(30)
    timer.timeout.connect(lambda: tick(service))
    timer.start()
    wait_qt(0.15)  # Exclude startup for both implementations.
    messages[0] = 0
    timings.clear()
    cycle_start = cpu_cycles()
    cpu, start = time.process_time(), time.perf_counter()
    wait_qt(seconds)
    timer.stop()
    wall, cpu = time.perf_counter() - start, time.process_time() - cpu
    cycles = cpu_cycles() - cycle_start
    rss = psutil.Process().memory_info().rss
    if service._meter:
        service._meter.stop()
        service._meter._thread.join(2)
    queue.close()
    return {"roles":count,"enabled":enabled,"wall_s":wall,"python_cpu_s":cpu,
        "python_cpu_percent_one_core":cpu / wall * 100,"scale_ipc_per_s":messages[0] / wall,
        "python_cpu_cycles":cycles,"python_cycles_per_s":cycles / wall,
        "python_rss_bytes":rss,"audio_reads":len(timings),
        "mean_audio_read_ns":statistics.fmean(timings) if timings else None}


def new_run(count, seconds, enabled, binary, consumer):
    import psutil
    from PySide6.QtCore import QCoreApplication
    from bandori_ui.native_pet_services import NativePetServices
    from bandori_core.shared_memory_ipc import SharedMemoryLineQueue, encode_ipc_envelope
    class BenchServices(NativePetServices):
        def _connect_plugins(self, app):
            pass
    queue = SharedMemoryLineQueue.create("music-benchmark-" + uuid.uuid4().hex)
    changed = []
    scale_messages = [0]
    def broadcast(line):
        if line.startswith("NATIVE_MUSIC_SOURCE\t"):
            changed.append(line)
        elif line.startswith("NATIVE_CONTROL\t") and json.loads(line.split("\t", 1)[1]).get("command") == "music_scale":
            scale_messages[0] += 1
        assert queue.publish(encode_ipc_envelope("benchmark", line))
    service = BenchServices(QCoreApplication.instance(), {"music_bounce_enabled":enabled}, None, broadcast, lambda _: None)
    manager = service._music
    manager._diagnostics = True
    processes = []
    try:
        service.configure_models([{"character":str(i)} for i in range(count)])
        deadline = time.monotonic() + 5
        while enabled and manager.path is None and time.monotonic() < deadline:
            QCoreApplication.processEvents()
            time.sleep(0.005)
        if enabled and manager.path is None:
            raise RuntimeError("native service did not become ready")
        for _ in range(count):
            processes.append(subprocess.Popen([str(consumer), manager.path if enabled else "disabled", str(seconds + 1), "60"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        wait_qt(0.1)
        watched = [psutil.Process(p.pid) for p in processes]
        if enabled:
            watched.append(psutil.Process(manager._process.processId()))
        before = [sum(p.cpu_times()[:2]) for p in watched]
        rss = [p.memory_info().rss for p in watched]
        native_cycles_before = [cpu_cycles(p.pid) for p in watched]
        cycle_start = cpu_cycles()
        cpu, start = time.process_time(), time.perf_counter()
        initial_changes = len(changed)
        initial_scales = scale_messages[0]
        wait_qt(seconds)
        wall, cpu = time.perf_counter() - start, time.process_time() - cpu
        cycles = cpu_cycles() - cycle_start
        native_cycles = [cpu_cycles(p.pid) - old for p, old in zip(watched, native_cycles_before)]
        python_rss = psutil.Process().memory_info().rss
        native_cpu = [sum(p.cpu_times()[:2]) - old for p, old in zip(watched, before)]
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=5)
            if process.returncode:
                raise RuntimeError(stderr)
            results.append(json.loads(stdout))
        steady_changes = len(changed) - initial_changes
        manager.close()
        return {"roles":count,"enabled":enabled,"wall_s":wall,"python_cpu_s":cpu,
            "python_cpu_percent_one_core":cpu / wall * 100,
            "python_cpu_cycles":cycles,"python_cycles_per_s":cycles / wall,
            "scale_ipc_per_s":(scale_messages[0] - initial_scales) / wall,
            "python_rss_bytes":python_rss,
            "steady_source_notifications":steady_changes,"native_cpu_s":native_cpu,
            "native_cpu_cycles":native_cycles,
            "consumer_rss_bytes":rss[:count],"service_rss_bytes":rss[count:] or [],
            "consumer_timings":results,"service_metrics":manager.metrics}
    finally:
        service.close()
        service.deleteLater()
        QCoreApplication.processEvents()
        queue.close()
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=5)
    parser.add_argument("--roles", type=int, nargs="+", default=[1, 8])
    parser.add_argument("--profile", choices=["debug", "release"], default="debug")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("This before/after Core Audio benchmark requires Windows; use the physics example on other platforms.")
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    suffix = ".exe" if os.name == "nt" else ""
    directory = ROOT / "native/pet_backend/target" / args.profile
    binary = directory / ("bandori-pet-native" + suffix)
    consumer = directory / "examples" / ("music_benchmark" + suffix)
    os.environ["BANDORI_PET_NATIVE"] = str(binary)
    result = {"platform":platform.platform(),"python":sys.version,"profile":args.profile,
              "baseline_commit":BASELINE,"scope":__doc__,"old":[],"new":[]}
    result["native_physics"] = json.loads(subprocess.check_output([str(consumer), "physics"], text=True))
    module, _ = legacy()
    spring = module.MusicSpring()
    start = time.perf_counter_ns()
    for i in range(1_000_000):
        spring.step(0.8 if i % 30 < 5 else 0.0, 1 / 60)
    result["python_physics"] = {"updates":1_000_000,"mean_physics_ns":(time.perf_counter_ns()-start)/1_000_000}
    for enabled in [True, False]:
        for count in args.roles:
            print(f"Measuring enabled={enabled}, roles={count}", flush=True)
            result["old"].append(old_run(count, args.seconds, enabled))
            result["new"].append(new_run(count, args.seconds, enabled, binary, consumer))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(args.output)
    del app


if __name__ == "__main__":
    main()
