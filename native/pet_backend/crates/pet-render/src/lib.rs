//! wgpu rendering for the desktop pet window (spec §2.3).
//!
//! Frame order follows the Neocari viewer example: a mask pass into a small
//! offscreen atlas, then the main pass with `LoadOp::Clear(alpha = 0)`. Neocari's
//! shader outputs premultiplied alpha and its `Normal` blend state is
//! `One/OneMinusSrcAlpha`, which matches `CompositeAlphaMode::PreMultiplied` on a
//! transparent surface.
//!
//! The model always renders into an intermediate texture that is then blitted to
//! the swapchain. That single extra pass buys three things at once:
//!
//! * the "省电" quality tier (0.75× render resolution),
//! * window opacity without `WS_EX_LAYERED` colour-key hacks,
//! * a place to pre-multiply if a machine only offers `PostMultiplied` surfaces.

mod fps;

use std::sync::Arc;
use std::time::Instant;

use neocari::assets::DecodedTexture;
use neocari::core::Matrix44;
use neocari::moc3::{Moc3DrawableMesh, Moc3DrawableVertex};
use neocari::render::wgpu::{
    preferred_surface_format, WgpuClippingPlan, WgpuClippingResources, WgpuLive2dRenderer,
    WgpuMaskRenderTarget, WgpuMeshBuffers, WgpuTexture, WgpuTransform,
};
use tracing::{info, warn};
use winit::dpi::PhysicalSize;
use winit::window::Window;

/// Size of the clipping mask atlas (matches the Neocari example).
pub const MASK_TEXTURE_SIZE: u32 = 256;
/// Frames rendered before the circuit breaker trips (spec §2.3).
pub const FAILURE_FUSE: u32 = 3;

/// Rendering errors that must not kill the process.
#[derive(Debug, thiserror::Error)]
pub enum RenderError {
    /// No suitable GPU adapter.
    #[error("no suitable GPU adapter: {0}")]
    Adapter(String),
    /// Device creation failed.
    #[error("failed to create device: {0}")]
    Device(String),
    /// The surface cannot present.
    #[error("surface unsupported by adapter")]
    UnsupportedSurface,
    /// The adapter cannot composite a transparent window.
    #[error("surface does not support transparent alpha compositing")]
    UnsupportedTransparency,
    /// Surface texture acquisition failed.
    #[error("failed to acquire surface texture: {0}")]
    Acquire(String),
    /// Neocari draw call failed.
    #[error("draw failed: {0}")]
    Draw(String),
    /// Mesh upload failed.
    #[error("mesh upload failed")]
    MeshUpload,
    /// Clipping resources failed.
    #[error("clipping setup failed: {0}")]
    Clipping(String),
    /// Texture upload failed.
    #[error("texture upload failed: {0}")]
    Texture(String),
}

/// Shared GPU device, queue and Live2D pipelines.
pub struct Gpu {
    /// wgpu instance.
    pub instance: wgpu::Instance,
    /// Chosen adapter.
    pub adapter: wgpu::Adapter,
    /// Logical device.
    pub device: wgpu::Device,
    /// Queue.
    pub queue: wgpu::Queue,
    /// Adapter description for the About page.
    pub adapter_info: wgpu::AdapterInfo,
}

impl Gpu {
    /// Creates a device. `allow_hardware` mirrors `gpu_acceleration`.
    pub fn new(
        allow_hardware: bool,
        compatible_surface: Option<&wgpu::Surface<'static>>,
    ) -> Result<Self, RenderError> {
        if compatible_surface.is_none() {
            return Self::create_preferred(allow_hardware, None).map(|(gpu, _)| gpu);
        }
        let instance = wgpu::Instance::new(wgpu::InstanceDescriptor::new_without_display_handle());
        Self::new_from(instance, allow_hardware, compatible_surface)
    }

    fn create_preferred(
        allow_hardware: bool,
        window: Option<Arc<Window>>,
    ) -> Result<(Self, Option<wgpu::Surface<'static>>), RenderError> {
        // Windows pets need an explicitly alpha-composited DirectComposition
        // swapchain. Vulkan WSI may expose only Opaque/Inherit, and the default
        // DX12 HWND swapchain ignores alpha entirely. Both can turn transparent
        // pixels black on Windows 11, even when winit requests transparency.
        #[cfg(windows)]
        if window.is_some() {
            return Self::create_on_backends(allow_hardware, window, wgpu::Backends::DX12);
        }

        // wgpu sorts by device class, with Vulkan first for equal classes on
        // Windows. A Vulkan discrete GPU (or a requested CPU adapter) already
        // wins that search. Avoid initializing DX12/GL and their driver heaps
        // just to discard their adapters. Less preferred classes and failures
        // still use the full search, preserving cross-backend GPU selection.
        #[cfg(windows)]
        if let Ok(candidate) =
            Self::create_on_backends(allow_hardware, window.clone(), wgpu::Backends::VULKAN)
        {
            if preferred_device_class(allow_hardware, candidate.0.adapter_info.device_type) {
                return Ok(candidate);
            }
        }
        Self::create_on_backends(allow_hardware, window, wgpu::Backends::all())
    }

    fn create_on_backends(
        allow_hardware: bool,
        window: Option<Arc<Window>>,
        backends: wgpu::Backends,
    ) -> Result<(Self, Option<wgpu::Surface<'static>>), RenderError> {
        let descriptor = wgpu::InstanceDescriptor {
            backends,
            ..wgpu::InstanceDescriptor::new_without_display_handle()
        };
        #[cfg(windows)]
        let descriptor = {
            let mut descriptor = descriptor;
            if window.is_some() {
                descriptor.backend_options.dx12.presentation_system =
                    wgpu::Dx12SwapchainKind::DxgiFromVisual;
            }
            descriptor
        };
        let instance = wgpu::Instance::new(descriptor);
        let surface = window
            .map(|window| instance.create_surface(window))
            .transpose()
            .map_err(|error| RenderError::Adapter(error.to_string()))?;
        let gpu = Self::new_from(instance, allow_hardware, surface.as_ref())?;
        Ok((gpu, surface))
    }

    /// Creates a device on an existing instance (so the surface stays valid).
    pub fn new_from(
        instance: wgpu::Instance,
        allow_hardware: bool,
        compatible_surface: Option<&wgpu::Surface<'static>>,
    ) -> Result<Self, RenderError> {
        let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: if allow_hardware {
                wgpu::PowerPreference::HighPerformance
            } else {
                wgpu::PowerPreference::LowPower
            },
            force_fallback_adapter: !allow_hardware,
            compatible_surface,
            apply_limit_buckets: false,
        }))
        .map_err(|error| RenderError::Adapter(error.to_string()))?;

        let (device, queue) = pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor {
            label: Some("bandori-pet.device"),
            required_features: wgpu::Features::empty(),
            required_limits: wgpu::Limits::default(),
            // Desktop pets use small, mostly persistent resources. Avoid the
            // large allocation blocks intended for games; texture dimensions,
            // render precision and frame scheduling stay unchanged.
            memory_hints: wgpu::MemoryHints::MemoryUsage,
            ..Default::default()
        }))
        .map_err(|error| RenderError::Device(error.to_string()))?;

        let adapter_info = adapter.get_info();
        info!(
            adapter = %adapter_info.name,
            backend = ?adapter_info.backend,
            driver = %adapter_info.driver,
            "renderer initialised"
        );
        Ok(Self {
            instance,
            adapter,
            device,
            queue,
            adapter_info,
        })
    }
}

#[cfg(windows)]
fn preferred_device_class(allow_hardware: bool, device_type: wgpu::DeviceType) -> bool {
    device_type
        == if allow_hardware {
            wgpu::DeviceType::DiscreteGpu
        } else {
            wgpu::DeviceType::Cpu
        }
}

/// The swapchain plus its configuration.
pub struct Surface {
    surface: wgpu::Surface<'static>,
    config: wgpu::SurfaceConfiguration,
    alpha_mode: wgpu::CompositeAlphaMode,
    vsync: bool,
    dpr: f64,
}

impl Surface {
    /// Creates and configures a surface for `window`.
    pub fn new(gpu: &Gpu, window: Arc<Window>, vsync: bool) -> Result<Self, RenderError> {
        let surface = gpu
            .instance
            .create_surface(Arc::clone(&window))
            .map_err(|error| RenderError::Adapter(error.to_string()))?;
        Self::from_existing(gpu, surface, window, vsync)
    }

    /// Configures an already-created surface (the one the adapter was probed with).
    fn from_existing(
        gpu: &Gpu,
        surface: wgpu::Surface<'static>,
        window: Arc<Window>,
        vsync: bool,
    ) -> Result<Self, RenderError> {
        let capabilities = surface.get_capabilities(&gpu.adapter);
        if capabilities.formats.is_empty() {
            return Err(RenderError::UnsupportedSurface);
        }
        let size = window.inner_size();
        let mut config = surface
            .get_default_config(&gpu.adapter, size.width.max(1), size.height.max(1))
            .ok_or(RenderError::UnsupportedSurface)?;
        config.format = preferred_surface_format(&capabilities.formats)
            .ok_or(RenderError::UnsupportedSurface)?;
        let alpha_mode = choose_alpha_mode(&capabilities.alpha_modes)
            .ok_or(RenderError::UnsupportedTransparency)?;
        config.alpha_mode = alpha_mode;
        config.present_mode = choose_present_mode(&capabilities.present_modes, vsync);
        config.desired_maximum_frame_latency = 3;
        surface.configure(&gpu.device, &config);
        info!(
            format = ?config.format,
            alpha = ?alpha_mode,
            present = ?config.present_mode,
            "surface configured"
        );
        Ok(Self {
            surface,
            config,
            alpha_mode,
            vsync,
            dpr: window.scale_factor(),
        })
    }

    /// Current size in physical pixels.
    pub fn size(&self) -> (u32, u32) {
        (self.config.width, self.config.height)
    }

    /// Current device pixel ratio.
    pub fn dpr(&self) -> f64 {
        self.dpr
    }

    /// Surface format.
    pub fn format(&self) -> wgpu::TextureFormat {
        self.config.format
    }

    /// Alpha mode in use.
    pub fn alpha_mode(&self) -> wgpu::CompositeAlphaMode {
        self.alpha_mode
    }

    /// `true` when vsync is requested.
    pub fn vsync(&self) -> bool {
        self.vsync
    }

    /// Resizes the swapchain (no-op for zero sizes).
    pub fn resize(&mut self, gpu: &Gpu, size: PhysicalSize<u32>, dpr: f64) {
        self.dpr = dpr;
        if size.width == 0 || size.height == 0 {
            return;
        }
        if self.config.width == size.width && self.config.height == size.height {
            return;
        }
        self.config.width = size.width;
        self.config.height = size.height;
        self.surface.configure(&gpu.device, &self.config);
    }

    /// Re-applies configuration after a vsync change.
    pub fn reconfigure(&mut self, gpu: &Gpu, vsync: bool) {
        self.vsync = vsync;
        self.config.present_mode = choose_present_mode(
            &self.surface.get_capabilities(&gpu.adapter).present_modes,
            vsync,
        );
        self.surface.configure(&gpu.device, &self.config);
    }

    /// Recreates the swapchain after a lost/outdated frame.
    pub fn recreate(&mut self, gpu: &Gpu) {
        self.surface.configure(&gpu.device, &self.config);
    }

    fn acquire(&self) -> Result<Option<wgpu::SurfaceTexture>, RenderError> {
        match self.surface.get_current_texture() {
            wgpu::CurrentSurfaceTexture::Success(frame) => Ok(Some(frame)),
            wgpu::CurrentSurfaceTexture::Suboptimal(frame) => Ok(Some(frame)),
            wgpu::CurrentSurfaceTexture::Timeout | wgpu::CurrentSurfaceTexture::Occluded => {
                // AppKit's occlusion state can lag behind orderFront, and a
                // covered window may stay occluded indefinitely. Neither is a
                // draw failure; keep the renderer available for the next frame.
                Ok(None)
            }
            wgpu::CurrentSurfaceTexture::Outdated => {
                Err(RenderError::Acquire("outdated".to_owned()))
            }
            wgpu::CurrentSurfaceTexture::Lost => Err(RenderError::Acquire("lost".to_owned())),
            wgpu::CurrentSurfaceTexture::Validation => {
                Err(RenderError::Acquire("validation".to_owned()))
            }
        }
    }
}

fn choose_alpha_mode(modes: &[wgpu::CompositeAlphaMode]) -> Option<wgpu::CompositeAlphaMode> {
    // Auto may select Opaque and silently discard the transparent clear colour.
    // Inherit is useful on platforms where winit configures native visual alpha.
    [
        wgpu::CompositeAlphaMode::PreMultiplied,
        wgpu::CompositeAlphaMode::PostMultiplied,
        wgpu::CompositeAlphaMode::Inherit,
    ]
    .into_iter()
    .find(|mode| modes.contains(mode))
}

fn choose_present_mode(modes: &[wgpu::PresentMode], vsync: bool) -> wgpu::PresentMode {
    if vsync {
        if modes.contains(&wgpu::PresentMode::Fifo) {
            wgpu::PresentMode::Fifo
        } else {
            wgpu::PresentMode::AutoVsync
        }
    } else if modes.contains(&wgpu::PresentMode::AutoNoVsync) {
        wgpu::PresentMode::AutoNoVsync
    } else if modes.contains(&wgpu::PresentMode::Immediate) {
        wgpu::PresentMode::Immediate
    } else {
        wgpu::PresentMode::AutoVsync
    }
}

/// GPU state for one loaded model.
pub struct ModelGpu {
    mesh_buffers: WgpuMeshBuffers,
    textures: Vec<WgpuTexture>,
    clipping_plan: WgpuClippingPlan,
    clipping: WgpuClippingResources,
    mask_target: WgpuMaskRenderTarget,
    transform: WgpuTransform,
    drawable_count: usize,
}

impl ModelGpu {
    /// Uploads meshes and textures and builds the clipping resources.
    pub fn new(
        gpu: &Gpu,
        renderer: &WgpuLive2dRenderer,
        meshes: &[Moc3DrawableMesh],
        textures: &[DecodedTexture],
        matrix: Matrix44,
    ) -> Result<Self, RenderError> {
        let mesh_buffers =
            WgpuMeshBuffers::from_drawables(&gpu.device, meshes).ok_or(RenderError::MeshUpload)?;
        let mut uploaded = Vec::with_capacity(textures.len());
        for texture in textures {
            let uploaded_texture = renderer
                .create_rgba8_texture(
                    &gpu.device,
                    &gpu.queue,
                    texture.width(),
                    texture.height(),
                    texture.rgba(),
                )
                .map_err(|error| RenderError::Texture(error.to_string()))?;
            uploaded.push(uploaded_texture);
        }
        let clipping_plan = prepare_clipping_plan(&mesh_buffers)?;
        let clipping = renderer
            .create_clipping_resources(&gpu.device, &clipping_plan)
            .map_err(|error| RenderError::Clipping(format!("{error:?}")))?;
        let mask_target = renderer
            .create_mask_render_target(&gpu.device, MASK_TEXTURE_SIZE)
            .map_err(|error| RenderError::Texture(error.to_string()))?;
        let transform = renderer.create_transform(&gpu.device, &matrix);
        let drawable_count = mesh_buffers.drawables().len();
        Ok(Self {
            mesh_buffers,
            textures: uploaded,
            clipping_plan,
            clipping,
            mask_target,
            transform,
            drawable_count,
        })
    }

    /// Re-uploads mesh vertices from a new frame.
    pub fn update_meshes(
        &mut self,
        gpu: &Gpu,
        renderer: &WgpuLive2dRenderer,
        meshes: &[Moc3DrawableMesh],
    ) -> Result<(), RenderError> {
        match self.mesh_buffers.update_drawables(&gpu.queue, meshes) {
            Ok(update) => {
                if update.bounds_changed() || update.visibility_changed() {
                    self.update_clipping(gpu, renderer, update.visibility_changed())?;
                }
                Ok(())
            }
            Err(_) => {
                self.mesh_buffers = WgpuMeshBuffers::from_drawables(&gpu.device, meshes)
                    .ok_or(RenderError::MeshUpload)?;
                self.drawable_count = self.mesh_buffers.drawables().len();
                self.update_clipping(gpu, renderer, true)
            }
        }
    }

    /// Updates the model → clip transform.
    pub fn set_matrix(&mut self, gpu: &Gpu, renderer: &WgpuLive2dRenderer, matrix: Matrix44) {
        if !self.transform.update_matrix(&gpu.queue, &matrix) {
            self.transform = renderer.create_transform(&gpu.device, &matrix);
        }
    }

    fn update_clipping(
        &mut self,
        gpu: &Gpu,
        renderer: &WgpuLive2dRenderer,
        regroup: bool,
    ) -> Result<(), RenderError> {
        // update_drawables validates mask topology before changing GPU data.
        // Bounds-only animation can reuse the groups and their allocations;
        // visibility changes and buffer replacement must regroup the plan.
        if regroup {
            self.clipping_plan = WgpuClippingPlan::from_mesh_buffers(&self.mesh_buffers);
        }
        self.clipping_plan
            .prepare_single_texture_masks(&self.mesh_buffers)
            .map_err(|error| RenderError::Clipping(format!("{error:?}")))?;
        if !renderer
            .update_clipping_resources(&gpu.queue, &mut self.clipping, &self.clipping_plan)
            .map_err(|error| RenderError::Clipping(format!("{error:?}")))?
        {
            self.clipping = renderer
                .create_clipping_resources(&gpu.device, &self.clipping_plan)
                .map_err(|error| RenderError::Clipping(format!("{error:?}")))?;
        }
        Ok(())
    }

    /// Number of drawables currently uploaded.
    pub fn drawable_count(&self) -> usize {
        self.drawable_count
    }

    /// Number of uploaded textures.
    pub fn texture_count(&self) -> usize {
        self.textures.len()
    }

    /// Reads the uploaded model into straight-alpha RGBA pixels without a window.
    pub fn capture_rgba(&self, gpu: &Gpu, width: u32, height: u32) -> Result<Vec<u8>, RenderError> {
        let renderer = WgpuLive2dRenderer::new(&gpu.device, wgpu::TextureFormat::Rgba8Unorm);
        render_model_offscreen(gpu, &renderer, self, width, height)
    }
}

fn prepare_clipping_plan(mesh_buffers: &WgpuMeshBuffers) -> Result<WgpuClippingPlan, RenderError> {
    let mut plan = WgpuClippingPlan::from_mesh_buffers(mesh_buffers);
    plan.prepare_single_texture_masks(mesh_buffers)
        .map_err(|error| RenderError::Clipping(format!("{error:?}")))?;
    Ok(plan)
}

/// Renders a single transparent preview without creating a native window.
/// The returned RGBA pixels use straight alpha, suitable for PNG and Slint.
pub fn render_preview(
    meshes: &[Moc3DrawableMesh],
    textures: &[DecodedTexture],
    matrix: Matrix44,
    width: u32,
    height: u32,
) -> Result<Vec<u8>, RenderError> {
    let gpu = Gpu::new(true, None)?;
    let format = wgpu::TextureFormat::Rgba8Unorm;
    let renderer = WgpuLive2dRenderer::new(&gpu.device, format);
    let model = ModelGpu::new(&gpu, &renderer, meshes, textures, matrix)?;
    render_model_offscreen(&gpu, &renderer, &model, width, height)
}

fn render_model_offscreen(
    gpu: &Gpu,
    renderer: &WgpuLive2dRenderer,
    model: &ModelGpu,
    width: u32,
    height: u32,
) -> Result<Vec<u8>, RenderError> {
    let format = wgpu::TextureFormat::Rgba8Unorm;
    let texture = gpu.device.create_texture(&wgpu::TextureDescriptor {
        label: Some("bandori-picker.preview"),
        size: wgpu::Extent3d {
            width,
            height,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
        view_formats: &[],
    });
    let view = texture.create_view(&Default::default());
    let stride = (width * 4).div_ceil(256) * 256;
    let buffer = gpu.device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("bandori-picker.readback"),
        size: stride as u64 * height as u64,
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });
    let mut encoder = gpu.device.create_command_encoder(&Default::default());
    for mask in [true, false] {
        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("bandori-picker.preview-pass"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: if mask {
                    model.mask_target.view()
                } else {
                    &view
                },
                depth_slice: None,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT),
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: None,
            timestamp_writes: None,
            occlusion_query_set: None,
            multiview_mask: None,
        });
        if mask {
            renderer.draw_masks_with_textures(
                &mut pass,
                &model.mesh_buffers,
                &model.clipping,
                &model.textures,
            )
        } else {
            renderer.draw_with_textures_clipping_and_transform(
                &mut pass,
                &model.mesh_buffers,
                &model.textures,
                &model.clipping,
                &model.mask_target,
                &model.transform,
            )
        }
        .map_err(|error| RenderError::Draw(error.to_string()))?;
    }
    encoder.copy_texture_to_buffer(
        texture.as_image_copy(),
        wgpu::TexelCopyBufferInfo {
            buffer: &buffer,
            layout: wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(stride),
                rows_per_image: Some(height),
            },
        },
        wgpu::Extent3d {
            width,
            height,
            depth_or_array_layers: 1,
        },
    );
    gpu.queue.submit([encoder.finish()]);
    let (tx, rx) = std::sync::mpsc::channel();
    buffer
        .slice(..)
        .map_async(wgpu::MapMode::Read, move |result| {
            let _ = tx.send(result);
        });
    gpu.device
        .poll(wgpu::PollType::wait_indefinitely())
        .map_err(|error| RenderError::Draw(error.to_string()))?;
    rx.recv()
        .map_err(|error| RenderError::Draw(error.to_string()))?
        .map_err(|error| RenderError::Draw(error.to_string()))?;
    let mapped = buffer
        .slice(..)
        .get_mapped_range()
        .map_err(|error| RenderError::Draw(error.to_string()))?;
    let mut pixels = Vec::with_capacity((width * height * 4) as usize);
    for row in mapped.chunks(stride as usize) {
        for pixel in row[..width as usize * 4].chunks_exact(4) {
            let alpha = pixel[3] as u32;
            for channel in &pixel[..3] {
                pixels.push(
                    (*channel as u32 * 255 + alpha / 2)
                        .checked_div(alpha)
                        .unwrap_or(0)
                        .min(255) as u8,
                );
            }
            pixels.push(pixel[3]);
        }
    }
    drop(mapped);
    buffer.unmap();
    Ok(pixels)
}

/// Blit pipeline used for the downscale and opacity pass.
struct Blit {
    pipeline: wgpu::RenderPipeline,
    bind_group_layout: wgpu::BindGroupLayout,
    sampler: wgpu::Sampler,
    opacity: wgpu::Buffer,
}

impl Blit {
    fn new(device: &wgpu::Device, format: wgpu::TextureFormat) -> Self {
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("bandori-pet.blit"),
            source: wgpu::ShaderSource::Wgsl(include_str!("../shaders/blit.wgsl").into()),
        });
        let bind_group_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("bandori-pet.blit.layout"),
            entries: &[
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 2,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Buffer {
                        ty: wgpu::BufferBindingType::Uniform,
                        has_dynamic_offset: false,
                        min_binding_size: None,
                    },
                    count: None,
                },
            ],
        });
        let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("bandori-pet.blit.pipeline_layout"),
            bind_group_layouts: &[Some(&bind_group_layout)],
            immediate_size: 0,
        });
        let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("bandori-pet.blit.pipeline"),
            layout: Some(&layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs_blit"),
                compilation_options: wgpu::PipelineCompilationOptions::default(),
                buffers: &[],
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("fs_blit"),
                compilation_options: wgpu::PipelineCompilationOptions::default(),
                targets: &[Some(wgpu::ColorTargetState {
                    format,
                    blend: Some(wgpu::BlendState::REPLACE),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            primitive: wgpu::PrimitiveState::default(),
            depth_stencil: None,
            multisample: wgpu::MultisampleState::default(),
            multiview_mask: None,
            cache: None,
        });
        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("bandori-pet.blit.sampler"),
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });
        let opacity = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("bandori-pet.blit.opacity"),
            size: 16,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        Self {
            pipeline,
            bind_group_layout,
            sampler,
            opacity,
        }
    }

    fn set_opacity(&self, queue: &wgpu::Queue, opacity: f32) {
        let value = opacity.clamp(0.0, 1.0);
        queue.write_buffer(
            &self.opacity,
            0,
            bytemuck::cast_slice(&[value, 0.0f32, 0.0, 0.0]),
        );
    }

    fn bind_group(&self, device: &wgpu::Device, view: &wgpu::TextureView) -> wgpu::BindGroup {
        device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("bandori-pet.blit.bind_group"),
            layout: &self.bind_group_layout,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(view),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(&self.sampler),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: self.opacity.as_entire_binding(),
                },
            ],
        })
    }
}

/// A render-resolution-scaled intermediate target.
struct Intermediate {
    view: wgpu::TextureView,
    blit_bind_group: wgpu::BindGroup,
    width: u32,
    height: u32,
}

impl Intermediate {
    fn new(
        device: &wgpu::Device,
        width: u32,
        height: u32,
        format: wgpu::TextureFormat,
        blit: &Blit,
    ) -> Self {
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("bandori-pet.intermediate"),
            size: wgpu::Extent3d {
                width: width.max(1),
                height: height.max(1),
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
            view_formats: &[],
        });
        let view = texture.create_view(&wgpu::TextureViewDescriptor::default());
        let blit_bind_group = blit.bind_group(device, &view);
        Self {
            view,
            blit_bind_group,
            width: width.max(1),
            height: height.max(1),
        }
    }
}

struct FpsOverlay {
    buffers: WgpuMeshBuffers,
    texture: WgpuTexture,
    transform: WgpuTransform,
    size: (u32, u32),
    dpr: f64,
}

impl FpsOverlay {
    fn new(
        gpu: &Gpu,
        renderer: &WgpuLive2dRenderer,
        size: (u32, u32),
        dpr: f64,
        text: &str,
    ) -> Result<Self, RenderError> {
        let (width, height, pixels) = fps::rasterize(text);
        let texture = renderer
            .create_rgba8_texture(&gpu.device, &gpu.queue, width, height, &pixels)
            .map_err(|e| RenderError::Texture(e.to_string()))?;
        let scale = dpr.max(1.0) as f32;
        let x = 6.0 * scale;
        let y = 6.0 * scale;
        let left = x / size.0 as f32 * 2.0 - 1.0;
        let right = (x + width as f32 * scale) / size.0 as f32 * 2.0 - 1.0;
        let top = 1.0 - y / size.1 as f32 * 2.0;
        let bottom = 1.0 - (y + height as f32 * scale) / size.1 as f32 * 2.0;
        let mesh = Moc3DrawableMesh::from_parts(
            0,
            0,
            1.0,
            0.0,
            vec![
                Moc3DrawableVertex::new([left, top], [0.0, 0.0]),
                Moc3DrawableVertex::new([right, top], [1.0, 0.0]),
                Moc3DrawableVertex::new([right, bottom], [1.0, 1.0]),
                Moc3DrawableVertex::new([left, bottom], [0.0, 1.0]),
            ],
            vec![0, 1, 2, 0, 2, 3],
            Vec::new(),
        );
        let buffers =
            WgpuMeshBuffers::from_drawables(&gpu.device, &[mesh]).ok_or(RenderError::MeshUpload)?;
        let transform = renderer.create_transform(&gpu.device, &Matrix44::identity());
        Ok(Self {
            buffers,
            texture,
            transform,
            size,
            dpr,
        })
    }
}

/// One role window's renderer: swapchain, blit, intermediate target.
pub struct SceneRenderer {
    gpu: Arc<Gpu>,
    /// Neocari pipelines for this surface's format.
    renderer: WgpuLive2dRenderer,
    /// Surface format the pipelines were built for.
    format: wgpu::TextureFormat,
    surface: Surface,
    blit: Blit,
    intermediate: Intermediate,
    quality: f32,
    opacity: f32,
    consecutive_failures: u32,
    fused: bool,
    frames: u64,
    fps_meter: Option<fps::FpsMeter>,
    fps_overlay: Option<FpsOverlay>,
}

impl SceneRenderer {
    /// Read the current native model frame for explicitly enabled outfit recognition.
    pub fn capture_rgba(
        &self,
        model: &ModelGpu,
        width: u32,
        height: u32,
    ) -> Result<Vec<u8>, RenderError> {
        model.capture_rgba(&self.gpu, width, height)
    }

    /// Creates the GPU (or shares `gpu`) and configures a surface for `window`.
    pub fn new(
        window: Arc<Window>,
        vsync: bool,
        quality: f32,
        opacity: f32,
        allow_hardware: bool,
    ) -> Result<Self, RenderError> {
        // The surface has to exist before the adapter request so the adapter is
        // guaranteed to be compatible with this window. The very same surface is
        // then configured: creating a throwaway probe surface and dropping it
        // leaves dangling `SurfaceId`s inside wgpu.
        let (gpu, probe_surface) =
            Gpu::create_preferred(allow_hardware, Some(Arc::clone(&window)))?;
        let gpu = Arc::new(gpu);
        let probe_surface = probe_surface.expect("window supplied for surface creation");
        let surface = Surface::from_existing(&gpu, probe_surface, window, vsync)?;
        let format = surface.format();
        let renderer = WgpuLive2dRenderer::new(&gpu.device, format);
        let blit = Blit::new(&gpu.device, surface.format());
        blit.set_opacity(&gpu.queue, opacity);
        let (width, height) = surface.size();
        let intermediate = Intermediate::new(
            &gpu.device,
            scale_dim(width, quality),
            scale_dim(height, quality),
            surface.format(),
            &blit,
        );
        Ok(Self {
            gpu,
            renderer,
            format,
            surface,
            blit,
            intermediate,
            quality,
            opacity,
            consecutive_failures: 0,
            fused: false,
            frames: 0,
            fps_meter: None,
            fps_overlay: None,
        })
    }

    /// Reuses an existing device for an additional role window.
    pub fn with_gpu(
        gpu: Arc<Gpu>,
        window: Arc<Window>,
        vsync: bool,
        quality: f32,
        opacity: f32,
    ) -> Result<Self, RenderError> {
        let surface = Surface::new(&gpu, window, vsync)?;
        // Pipelines are format specific; every role builds its own for its surface.
        let format = surface.format();
        let renderer = WgpuLive2dRenderer::new(&gpu.device, format);
        let blit = Blit::new(&gpu.device, format);
        blit.set_opacity(&gpu.queue, opacity);
        let (width, height) = surface.size();
        let intermediate = Intermediate::new(
            &gpu.device,
            scale_dim(width, quality),
            scale_dim(height, quality),
            surface.format(),
            &blit,
        );
        Ok(Self {
            gpu,
            renderer,
            format,
            surface,
            blit,
            intermediate,
            quality,
            opacity,
            consecutive_failures: 0,
            fused: false,
            frames: 0,
            fps_meter: None,
            fps_overlay: None,
        })
    }

    /// The shared device.
    pub fn gpu(&self) -> &Arc<Gpu> {
        &self.gpu
    }

    /// The Live2D pipelines used by this surface.
    pub fn renderer(&self) -> &WgpuLive2dRenderer {
        &self.renderer
    }

    /// GPU info for the About page.
    pub fn adapter_info(&self) -> &wgpu::AdapterInfo {
        &self.gpu.adapter_info
    }

    /// Surface format the model pipelines were built for.
    pub fn format(&self) -> wgpu::TextureFormat {
        self.format
    }

    /// Surface size in physical pixels.
    pub fn size(&self) -> (u32, u32) {
        self.surface.size()
    }

    /// Device pixel ratio.
    pub fn dpr(&self) -> f64 {
        self.surface.dpr()
    }

    /// Alpha mode negotiated with the compositor.
    pub fn alpha_mode(&self) -> wgpu::CompositeAlphaMode {
        self.surface.alpha_mode()
    }

    /// `true` when vsync is active.
    pub fn vsync(&self) -> bool {
        self.surface.vsync()
    }

    /// Frames presented since start-up.
    pub fn frames(&self) -> u64 {
        self.frames
    }

    /// `true` when the circuit breaker tripped (rendering stays stopped).
    pub fn is_fused(&self) -> bool {
        self.fused
    }

    /// Current render-resolution scale.
    pub fn quality(&self) -> f32 {
        self.quality
    }

    /// Switches the render-resolution scale.
    pub fn set_quality(&mut self, quality: f32) {
        self.quality = quality.clamp(0.25, 1.0);
        self.resize_intermediate();
    }

    fn resize_intermediate(&mut self) {
        let (width, height) = self.surface.size();
        let width = scale_dim(width, self.quality);
        let height = scale_dim(height, self.quality);
        if (self.intermediate.width, self.intermediate.height) == (width, height) {
            return;
        }
        self.intermediate = Intermediate::new(
            &self.gpu.device,
            width,
            height,
            self.surface.format(),
            &self.blit,
        );
    }

    /// Shows or hides the measured frame rate.
    pub fn set_show_fps(&mut self, enabled: bool) {
        if enabled != self.fps_meter.is_some() {
            self.fps_meter = enabled.then(|| fps::FpsMeter::new(Instant::now()));
            self.fps_overlay = None;
        }
    }

    /// Applies window opacity (multiplied into the blit).
    pub fn set_opacity(&mut self, opacity: f32) {
        self.opacity = opacity.clamp(0.0, 1.0);
        self.blit.set_opacity(&self.gpu.queue, self.opacity);
    }

    /// Resizes the swapchain and the intermediate target.
    pub fn resize(&mut self, size: PhysicalSize<u32>, dpr: f64) {
        self.surface.resize(&self.gpu, size, dpr);
        self.resize_intermediate();
    }

    /// Re-applies the vsync preference.
    pub fn set_vsync(&mut self, vsync: bool) {
        self.surface.reconfigure(&self.gpu, vsync);
    }

    /// Uploads a freshly loaded model.
    pub fn upload_model(
        &self,
        meshes: &[Moc3DrawableMesh],
        textures: &[DecodedTexture],
        matrix: Matrix44,
    ) -> Result<ModelGpu, RenderError> {
        ModelGpu::new(&self.gpu, &self.renderer, meshes, textures, matrix)
    }

    /// Renders one frame of `model` into the swapchain. Returns `false` when
    /// no frame was presented (occlusion, a temporary timeout, or a fused renderer).
    pub fn render(&mut self, model: &ModelGpu) -> Result<bool, RenderError> {
        if self.fused {
            return Ok(false);
        }
        if let Some(meter) = &self.fps_meter {
            let size = self.surface.size();
            let dpr = self.surface.dpr();
            if self
                .fps_overlay
                .as_ref()
                .is_none_or(|overlay| overlay.size != size || overlay.dpr != dpr)
            {
                self.fps_overlay = Some(FpsOverlay::new(
                    &self.gpu,
                    &self.renderer,
                    size,
                    dpr,
                    &meter.text,
                )?);
            }
        }
        let result = self.render_inner(model);
        match &result {
            Ok(true) => {
                self.consecutive_failures = 0;
                self.frames += 1;
                if self
                    .fps_meter
                    .as_mut()
                    .is_some_and(|meter| meter.record(Instant::now()))
                {
                    self.fps_overlay = None;
                }
            }
            Ok(false) => {}
            Err(error) => {
                self.consecutive_failures += 1;
                warn!(%error, failures = self.consecutive_failures, "frame failed");
                if let RenderError::Acquire(reason) = error {
                    if reason == "outdated" || reason == "lost" {
                        self.surface.recreate(&self.gpu);
                    }
                }
                if self.consecutive_failures >= FAILURE_FUSE {
                    self.fused = true;
                    warn!("renderer fused after repeated failures");
                }
            }
        }
        result
    }

    fn render_inner(&mut self, model: &ModelGpu) -> Result<bool, RenderError> {
        let Some(frame) = self.surface.acquire()? else {
            return Ok(false);
        };
        let frame_view = frame
            .texture
            .create_view(&wgpu::TextureViewDescriptor::default());
        let mut encoder = self
            .gpu
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("bandori-pet.encoder"),
            });

        // Pass 0: clipping masks into the offscreen atlas.
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("bandori-pet.mask_pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: model.mask_target.view(),
                    depth_slice: None,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            self.renderer
                .draw_masks_with_textures(
                    &mut pass,
                    &model.mesh_buffers,
                    &model.clipping,
                    &model.textures,
                )
                .map_err(|error| RenderError::Draw(error.to_string()))?;
        }

        // Pass 1: the model, into the intermediate target.
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("bandori-pet.main_pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &self.intermediate.view,
                    depth_slice: None,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            self.renderer
                .draw_with_textures_clipping_and_transform(
                    &mut pass,
                    &model.mesh_buffers,
                    &model.textures,
                    &model.clipping,
                    &model.mask_target,
                    &model.transform,
                )
                .map_err(|error| RenderError::Draw(error.to_string()))?;
            if let Some(overlay) = &self.fps_overlay {
                self.renderer
                    .draw_with_textures_and_transform(
                        &mut pass,
                        &overlay.buffers,
                        std::slice::from_ref(&overlay.texture),
                        &overlay.transform,
                    )
                    .map_err(|error| RenderError::Draw(error.to_string()))?;
            }
        }

        // Pass 2: blit to the swapchain (scale + opacity).
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("bandori-pet.blit_pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &frame_view,
                    depth_slice: None,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            pass.set_pipeline(&self.blit.pipeline);
            pass.set_bind_group(0, &self.intermediate.blit_bind_group, &[]);
            pass.draw(0..3, 0..1);
        }

        self.gpu.queue.submit([encoder.finish()]);
        self.gpu.queue.present(frame);
        Ok(true)
    }

    /// Intermediate target size (for the quality indicator).
    pub fn render_size(&self) -> (u32, u32) {
        (self.intermediate.width, self.intermediate.height)
    }
}

fn scale_dim(value: u32, quality: f32) -> u32 {
    ((value as f32) * quality).round().max(1.0) as u32
}

#[cfg(test)]
mod tests {
    use super::*;

    fn clipping_scene(frame: usize) -> Vec<Moc3DrawableMesh> {
        (0..4)
            .map(|i| {
                let shift = frame as f32 * 0.01;
                Moc3DrawableMesh::from_parts(
                    0,
                    0,
                    if (i == 0 && frame == 2)
                        || (i == 2 && frame == 3)
                        || (i % 2 == 0 && frame == 4)
                    {
                        0.0
                    } else {
                        1.0
                    },
                    i as f32,
                    vec![
                        Moc3DrawableVertex::new([-0.5 + shift, -0.5], [0.0, 1.0]),
                        Moc3DrawableVertex::new([0.5, -0.5 + shift], [1.0, 1.0]),
                        Moc3DrawableVertex::new([shift, 0.5], [0.5, 0.0]),
                    ],
                    vec![0, 1, 2],
                    if i % 2 == 0 { vec![1] } else { vec![] },
                )
            })
            .collect()
    }

    #[test]
    fn cached_clipping_matches_rebuilt_plans_through_visibility_and_topology_changes() {
        let instance = wgpu::Instance::new(wgpu::InstanceDescriptor {
            backends: wgpu::Backends::NOOP,
            backend_options: wgpu::BackendOptions {
                noop: wgpu::NoopBackendOptions {
                    enable: true,
                    ..Default::default()
                },
                ..Default::default()
            },
            ..wgpu::InstanceDescriptor::new_without_display_handle()
        });
        let gpu = Gpu::new_from(instance, true, None).unwrap();
        let renderer = WgpuLive2dRenderer::new(&gpu.device, wgpu::TextureFormat::Rgba8Unorm);
        let mut model = ModelGpu::new(
            &gpu,
            &renderer,
            &clipping_scene(0),
            &[],
            Matrix44::identity(),
        )
        .unwrap();
        for frame in 1..6 {
            let mut meshes = clipping_scene(frame);
            if frame == 5 {
                meshes[0] = Moc3DrawableMesh::from_parts(
                    0,
                    0,
                    1.0,
                    0.0,
                    meshes[0].vertices().to_vec(),
                    vec![0, 1, 2],
                    vec![3],
                );
            }
            model.update_meshes(&gpu, &renderer, &meshes).unwrap();
            let rebuilt = prepare_clipping_plan(&model.mesh_buffers).unwrap();
            assert_eq!(model.clipping_plan, rebuilt, "frame {frame}");
            for context in rebuilt.contexts() {
                for &index in context.drawable_indices() {
                    assert_eq!(
                        model
                            .clipping
                            .context_for_drawable(index)
                            .unwrap()
                            .drawable_indices(),
                        context.drawable_indices()
                    );
                }
            }
        }
    }

    #[test]
    fn alpha_mode_prefers_premultiplied() {
        assert_eq!(
            choose_alpha_mode(&[
                wgpu::CompositeAlphaMode::Opaque,
                wgpu::CompositeAlphaMode::PreMultiplied
            ]),
            Some(wgpu::CompositeAlphaMode::PreMultiplied)
        );
        assert_eq!(
            choose_alpha_mode(&[wgpu::CompositeAlphaMode::PostMultiplied]),
            Some(wgpu::CompositeAlphaMode::PostMultiplied)
        );
        assert_eq!(
            choose_alpha_mode(&[wgpu::CompositeAlphaMode::Inherit]),
            Some(wgpu::CompositeAlphaMode::Inherit)
        );
    }

    #[test]
    fn opaque_only_surfaces_do_not_silently_disable_transparency() {
        assert_eq!(choose_alpha_mode(&[wgpu::CompositeAlphaMode::Opaque]), None);
        assert_eq!(choose_alpha_mode(&[wgpu::CompositeAlphaMode::Auto]), None);
        assert_eq!(choose_alpha_mode(&[]), None);
    }

    #[cfg(windows)]
    #[test]
    #[ignore = "requires a Windows desktop and a DX12 adapter"]
    fn windows_surface_uses_direct_composition_across_reconfiguration() {
        use winit::event_loop::EventLoop;
        use winit::platform::windows::{EventLoopBuilderExtWindows, WindowAttributesExtWindows};

        let event_loop = EventLoop::builder().with_any_thread(true).build().unwrap();
        for allow_hardware in [true, false] {
            // This test owns a hidden HWND without running an application event loop.
            #[allow(deprecated)]
            let window = Arc::new(
                event_loop
                    .create_window(
                        Window::default_attributes()
                            .with_visible(false)
                            .with_decorations(false)
                            .with_transparent(true)
                            .with_no_redirection_bitmap(true)
                            .with_inner_size(PhysicalSize::new(64, 64)),
                    )
                    .unwrap(),
            );
            let mut renderer =
                SceneRenderer::new(Arc::clone(&window), true, 1.0, 1.0, allow_hardware).unwrap();
            assert_eq!(renderer.gpu.adapter_info.backend, wgpu::Backend::Dx12);
            if !allow_hardware {
                assert_eq!(renderer.gpu.adapter_info.device_type, wgpu::DeviceType::Cpu);
            }
            assert_eq!(
                renderer.alpha_mode(),
                wgpu::CompositeAlphaMode::PreMultiplied
            );
            let model = renderer
                .upload_model(&[], &[], Matrix44::identity())
                .unwrap();
            assert!(renderer.render(&model).unwrap());
            renderer.resize(PhysicalSize::new(96, 80), 1.0);
            renderer.set_vsync(false);
            renderer.surface.recreate(&renderer.gpu);
            renderer.set_opacity(0.5);
            for hittest in [false, true, false] {
                window.set_cursor_hittest(hittest).unwrap();
                assert!(renderer.render(&model).unwrap());
            }
            assert_eq!(
                renderer.alpha_mode(),
                wgpu::CompositeAlphaMode::PreMultiplied
            );
        }
    }

    #[test]
    fn present_mode_follows_vsync() {
        let modes = [wgpu::PresentMode::Fifo, wgpu::PresentMode::AutoNoVsync];
        assert_eq!(choose_present_mode(&modes, true), wgpu::PresentMode::Fifo);
        assert_eq!(
            choose_present_mode(&modes, false),
            wgpu::PresentMode::AutoNoVsync
        );
    }

    #[test]
    fn quality_scales_the_render_target() {
        assert_eq!(scale_dim(800, 0.75), 600);
        assert_eq!(scale_dim(801, 1.0), 801);
        assert_eq!(scale_dim(2, 0.25), 1);
    }
}
