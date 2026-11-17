# VRM 内存与渲染分配优化

本轮优化以 `6269d8b` 为基线，保持形变数值、纹理分辨率、动画步长和材质绘制顺序。

- 同一个 glTF accessor 的形变位置和法线只解码一次，用 `Arc<[Vec3]>` 在形变目标、primitive 和模型节点实例之间共享。缓存仅属于一次模型加载；卸载模型后没有全局缓存继续持有数据。不同 accessor 即使内容相同也不会错误合并。
- VRM 绘制顺序改用模型持有的索引缓冲。在顶点更新后原地排序，普通绘制和截图复用结果，避免每次绘制创建列表和稳定排序的临时分配。排序仍按材质队列、深度、原始 primitive 序号决定，深度相同时不会沿用上一帧的偶然顺序。

## 内存实测

Windows x64，Cargo 1.98.1，release 配置，使用现有 CPU 基准。工作负载为 10,201 个顶点、20,000 个三角形、48 个形变目标的合成 VRM；48 个目标引用同一个位置 accessor。每版预热 120 帧，测量 1,200 帧，前后交替运行三轮。

| 指标 | 基线 | 优化后 |
| --- | ---: | ---: |
| 常驻堆内存（字节，三轮一致） | 8,354,508 | 2,600,348 |
| 更新期峰值堆内存（字节，三轮一致） | 8,637,724 | 2,883,564 |
| 更新耗时中位数（三轮范围，毫秒） | 0.1008–0.1011 | 0.1022–0.1032 |
| 更新耗时 P95（三轮范围，毫秒） | 0.1049–0.1489 | 0.1684–0.2171 |

该工作负载减少约 5.49 MiB 常驻内存（68.9%）。耗时中位数基本持平，P95 在本机测试中较高，不据此声称 CPU 动画加速。额外用每版 12,000 帧、交替先后顺序复测，中位数分别为 0.1008–0.1010 / 0.1017–0.1023 毫秒，P95 分别为 0.1252–0.1640 / 0.1668–0.1712 毫秒。

这些数字仅包含 CPU 动画模型及基准自身的统计缓冲，不包含进程 RSS、GPU 显存或点击检测的 alpha 纹理。没有重复 accessor 的模型不会获得上述比例的节省；该合成数据用于验证重复引用场景，不能代表所有模型。CPU 基准不经过 GPU 绘制，因此不衡量绘制排序缓冲复用的收益。

## 复现

在修改前后各自构建并保留基准可执行文件，针对同一输入交替运行：

```powershell
python tools/benchmarks/vrm_workload.py .runtime/performance/grid-48-morphs.vrm
cargo build --release --manifest-path native/pet_backend/Cargo.toml -p pet-vrm --example runtime_benchmark --locked
native/pet_backend/target/release/examples/runtime_benchmark.exe .runtime/performance/grid-48-morphs.vrm 1200
```

验证命令：

```powershell
cargo test --manifest-path native/pet_backend/Cargo.toml --workspace --locked
cargo fmt --manifest-path native/pet_backend/Cargo.toml --all -- --check
python -m pytest tests/test_vrm_support.py tests/test_native_backend.py tests/test_native_preview.py tests/test_runtime_performance_optimizations.py -q
cargo build --release --manifest-path native/pet_backend/Cargo.toml -p bandori-pet-native --locked
```

新增回归检查覆盖形变共享、不同 accessor 和不同加载之间的隔离、释放缓存后的所有权，以及跨帧深度变化和相同深度下的绘制顺序。原有 VRM 0/1、形变标量参考、动画、物理和命中投影检查继续验证输出兼容性。

上述检查通过，Python 联动测试为 15 项通过、1 项跳过。另外显式运行了 Windows DirectComposition 硬件/软件适配器测试，以及 `tools/smoke_native_backend.py` 对 `minimal-vrm1.vrm` 的真实 GPU 窗口、IPC、动画更新和截图冒烟测试，均通过。
