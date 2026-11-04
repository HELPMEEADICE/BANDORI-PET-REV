# VRM 3D 桌宠

桌宠支持自包含的 VRM 0.x 和 VRM 1.0 文件，继续使用 **Rust + wgpu** 原生后端。
默认是**正面正交投影**：偏航 0°、俯仰 0°，没有透视缩放。VRM0/VRM1 的朝向差异会自动处理。
模型缩放按完整可绘制网格高度统一：`100%` 时与 MOC/MOC3 一样以 500 逻辑像素为基准，不受脸和身体比例影响。

## 使用

1. 构建原生后端：

   ```powershell
   cargo build --release --manifest-path native/pet_backend/Cargo.toml -p bandori-pet-native -p pet-assets --locked
   ```

2. 启动 `python main.py`，打开「设置 → 模型 → 导入自定义模型」，点击 **VRM (.vrm)**。
   也可以通过已有的文件夹或 ZIP 导入。模型须内嵌网格、纹理和缓冲区。
3. 输入角色名称，导入后在「自定义模型」分组选择角色。预览、缩放、透明背景、点击穿透、
   拖动、动作菜单、表情、眨眼、头部跟随、口型和多角色窗口继续共用现有流程。

本地测试模型 `C:\oss\MODELS\POPY\POPY\VRM\POPY_high.vrm` 已复制到
`models/POPY/default/POPY_high.vrm`，可直接选择 **POPY / default**。原始文件未修改。
`models/` 中的用户模型不会提交到 Git 或随安装包分发。

## MToon 材质

VRM 默认材质在原生 WGSL 中实现，自动读取 VRM0 `VRM/MToon` 参数或
VRM1 `VRMC_materials_mtoon` 扩展，包括：

- 主贴图、独立阴影贴图、阴影颜色、ShadeShift/Toony、shading grade/shift 贴图。
- 法线贴图、法线强度、MatCap、边缘光、自发光及其贴图。
- 世界空间或屏幕空间描边、描边宽度贴图、描边颜色和光照混合。
- Opaque / Mask / Blend、透明写深度、双面/剔除和材质绘制顺序。
- 主 UV 变换、滚动/旋转动画及遮罩；sRGB/线性颜色转换和预乘透明合成。

桌面环境采用固定白色方向光和柔和环境光。未实现 Unity 场景的阴影贴图、反射探针、
逐材质环境光球谐和后处理，因此不承诺与 Unity 截图逐像素一致。非 MToon 材质使用无光照回退。
当前所有材质贴图使用 UV0 和主 UV 变换；独立贴图的 UV 集/变换、完整 PBR 和 VRM1
节点约束不在本次支持范围内。

## 头发、衣服物理

读取模型自带的 VRM0 `secondaryAnimation` / VRM1 `VRMC_springBone`：
以 120 Hz 固定步长进行 Verlet 积分、阻尼、重力、骨长约束，以及球体/胶囊体碰撞。
处理顺序是动作 → 头部/呼吸姿态 → 弹簧骨骼 → Morph/蒙皮 → wgpu 深度渲染。
窗口拖动会给相同骨骼链施加惯性；暂停或窗口移动不改变物理步长。

POPY 有 **130 个弹簧骨骼关节**，覆盖头发、裙摆、袖子和衣饰。服装效果来自骨骼物理，
没有单独的布料网格求解器；没有配置弹簧骨骼的模型不会自动生成物理链。

## 动作

内置完整的自然待机和五个互动动作，替换了原来的测试抬手动作：

| 名称 | 动作和默认表情 |
|---|---|
| Idle | pixiv/ChatVRM 的约 10 秒全身待机，轻微重心变化、低强度自然笑容 |
| Wave | 双手挥手，配合柔和笑容 |
| LookAround | 环顾，轻微放松表情 |
| Thinking | 思考姿态，保持克制表情 |
| Relax | 放松姿态、浅笑 |
| Blush | 害羞姿态、低强度笑容 |

互动动作来自 tk256ailab/vrm-viewer。默认以原速度的 0.85–0.9 倍播放，动作切换有约
0.55 秒平滑过渡，待机循环有 0.65 秒首尾混合，一次性动作结束后自动过渡回待机。
旧配置中的 `SampleArm` 自动映射到 `Wave`，动作菜单中不再提供测试抬手动作。
源骨架的厘米/米缩放和录制起始位置会在重定向时处理，保持桌宠在原位。

笑容/眉眼使用模型自身的表情 Morph，VRM0 的 joy/fun 与 VRM1 的 happy/relaxed 自动对应。
表情、口型和头部跟随有缓动；眨眼使用长短变化的间隔，偶尔连续眨两次。
动作已嵌入二进制，运行时无需下载。来源、固定版本、校验和及 MIT 许可证见
[`third-party-notices.md`](../native/pet_backend/crates/pet-vrm/assets/third-party-notices.md)。

其他 VRMA 动作可放到模型附近，并建立同名的 `.pet.json`：

```text
POPY_high.vrm
POPY_high.pet.json
motions/wave.vrma
```

```json
{
  "camera": { "yaw": 0, "elevation": 0 },
  "motions": { "Wave": "motions/wave.vrma" },
  "default_motion": "Idle",
  "motion_settings": {
    "Idle": { "loop": true, "speed": 0.85 },
    "Wave": { "speed": 0.85, "fade": 0.65, "expression_strength": 0.32 }
  },
  "expression_strengths": { "joy": 0.5, "fun": 0.28 }
}
```

`camera` 可省略；无论角度如何始终使用正交投影。VRMA 按 humanoid 骨骼名重定向，支持
旋转、hips 位移、LINEAR / STEP / CUBICSPLINE 插值。`motion_settings` 可逐动作调整循环、
速度、过渡时长和配套表情强度；`expression_strengths` 控制手动选择表情时的强度。
VRMA 的表情和 LookAt 轨道尚未应用。模型自身的表情 Morph 可以通过表情菜单/口型驱动。
导入单个 VRM 时也会复制 `.pet.json` 和其中引用的相对路径动作。

## 验证

```powershell
cargo fmt --manifest-path native/pet_backend/Cargo.toml --all -- --check
cargo clippy --manifest-path native/pet_backend/Cargo.toml --workspace --all-targets --locked -- -D warnings
cargo test --manifest-path native/pet_backend/Cargo.toml --workspace --all-targets --locked
python -m pytest tests/test_vrm_support.py -q
```

使用真实模型进行动画、物理、GPU 出图和透明命中验证：

```powershell
cargo run --manifest-path native/pet_backend/Cargo.toml --example vrm_smoke --locked -- C:\oss\MODELS\POPY\POPY\VRM\POPY_high.vrm test-results/vrm/smoke 180
cargo run --manifest-path native/pet_backend/Cargo.toml --example window_smoke --locked -- C:\oss\MODELS\POPY\POPY\VRM\POPY_high.vrm
```

`vrm_smoke` 输出三张透明 PNG 和 JSON 指标；`window_smoke` 验证真实窗口的启动、隐藏、恢复和持续渲染。
静态预览也可指定动作和时间：

```powershell
native/pet_backend/target/release/bandori-pet-native.exe --render-preview models/POPY/default/POPY_high.vrm --output test-results/vrm/popy.png --motion Wave --time 2 --root .
```

固定正面构图的连续帧预览（含待机、进入动作、返回待机）：

```powershell
cargo run --manifest-path native/pet_backend/Cargo.toml --example vrm_motion_preview --locked -- models/POPY/default/POPY_high.vrm test-results/vrm/wave Wave 8 15
```
