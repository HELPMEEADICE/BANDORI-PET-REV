//! Depth-tested native wgpu VRM rendering on the existing transparent surface.
use crate::Gpu;
use neocari::core::Matrix44;
use pet_vrm::VrmModel;
use std::cell::RefCell;
use wgpu::util::DeviceExt;

struct Draw {
    vertex: wgpu::Buffer,
    index: wgpu::Buffer,
    count: u32,
    material: usize,
    depth: f32,
}
struct Material {
    group: wgpu::BindGroup,
    transparent: bool,
    cull: u32,
    depth_write: bool,
    outline: bool,
    queue: i32,
}
pub(crate) struct VrmGpu {
    draws: Vec<Draw>,
    materials: Vec<Material>,
    camera: wgpu::Buffer,
    camera_group: wgpu::BindGroup,
    pipelines: Vec<wgpu::RenderPipeline>,
    capture_pipelines: Vec<wgpu::RenderPipeline>,
    depth: RefCell<Option<(u32, u32, wgpu::TextureView)>>,
}
impl VrmGpu {
    pub fn new(gpu: &Gpu, model: &VrmModel, matrix: Matrix44, format: wgpu::TextureFormat) -> Self {
        let device = &gpu.device;
        let uniform_entry = |binding, visibility| wgpu::BindGroupLayoutEntry {
            binding,
            visibility,
            ty: wgpu::BindingType::Buffer {
                ty: wgpu::BufferBindingType::Uniform,
                has_dynamic_offset: false,
                min_binding_size: None,
            },
            count: None,
        };
        let camera_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("vrm.camera-layout"),
            entries: &[uniform_entry(0, wgpu::ShaderStages::VERTEX_FRAGMENT)],
        });
        let mut camera_data = matrix.as_slice().to_vec();
        camera_data.extend_from_slice(&[model.elapsed(), 1., 1., 0.05]);
        let camera = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("vrm.orthographic-camera"),
            contents: bytemuck::cast_slice(&camera_data),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });
        let camera_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("vrm.camera"),
            layout: &camera_layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: camera.as_entire_binding(),
            }],
        });
        let mut entries = Vec::new();
        for binding in 0..9 {
            entries.push(wgpu::BindGroupLayoutEntry {
                binding,
                visibility: wgpu::ShaderStages::VERTEX_FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            });
        }
        entries.push(wgpu::BindGroupLayoutEntry {
            binding: 9,
            visibility: wgpu::ShaderStages::VERTEX_FRAGMENT,
            ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
            count: None,
        });
        entries.push(uniform_entry(10, wgpu::ShaderStages::VERTEX_FRAGMENT));
        let material_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("vrm.mtoon-material-layout"),
            entries: &entries,
        });
        let mut textures = Vec::new();
        for texture in &model.textures {
            textures.push(upload_texture(
                gpu,
                texture.width(),
                texture.height(),
                texture.rgba(),
            ));
        }
        let white = upload_texture(gpu, 1, 1, &[255; 4]);
        let black = upload_texture(gpu, 1, 1, &[0, 0, 0, 255]);
        let normal = upload_texture(gpu, 1, 1, &[128, 128, 255, 255]);
        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("vrm.sampler"),
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            address_mode_u: wgpu::AddressMode::Repeat,
            address_mode_v: wgpu::AddressMode::Repeat,
            ..Default::default()
        });
        let materials = model
            .materials
            .iter()
            .map(|m| {
                let data = m.uniform();
                let uniform = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                    label: Some("vrm.material"),
                    contents: bytemuck::cast_slice(&data),
                    usage: wgpu::BufferUsages::UNIFORM,
                });
                let defaults = [
                    &white,
                    &white,
                    &normal,
                    &white,
                    &white,
                    &black,
                    &white,
                    &white,
                    if m.legacy { &white } else { &black },
                ];
                let mut entries: Vec<_> = m
                    .maps
                    .iter()
                    .enumerate()
                    .map(|(i, index)| wgpu::BindGroupEntry {
                        binding: i as u32,
                        resource: wgpu::BindingResource::TextureView(
                            index.and_then(|i| textures.get(i)).unwrap_or(defaults[i]),
                        ),
                    })
                    .collect();
                entries.push(wgpu::BindGroupEntry {
                    binding: 9,
                    resource: wgpu::BindingResource::Sampler(&sampler),
                });
                entries.push(wgpu::BindGroupEntry {
                    binding: 10,
                    resource: uniform.as_entire_binding(),
                });
                let group = device.create_bind_group(&wgpu::BindGroupDescriptor {
                    label: Some("vrm.mtoon-material"),
                    layout: &material_layout,
                    entries: &entries,
                });
                Material {
                    group,
                    transparent: m.transparent,
                    cull: m.cull.min(2),
                    depth_write: m.depth_write,
                    outline: m.outline_mode > 0 && m.outline_width > 0.,
                    queue: m.queue,
                }
            })
            .collect();
        let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("vrm.pipeline-layout"),
            bind_group_layouts: &[Some(&camera_layout), Some(&material_layout)],
            immediate_size: 0,
        });
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("vrm.toon"),
            source: wgpu::ShaderSource::Wgsl(include_str!("../shaders/vrm.wgsl").into()),
        });
        let make_pipelines = |format: wgpu::TextureFormat| {
            (0..11).map(|i| {
                let outline=i>=9;
                let vertex=if outline {"vs_outline"} else {"vs_main"};
                let fragment=match (outline,format.is_srgb()) {(false,false)=>"fs_main",(false,true)=>"fs_main_linear",(true,false)=>"fs_outline",(true,true)=>"fs_outline_linear"};
                device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
                    label:Some("vrm.mtoon-pipeline"),layout:Some(&layout),
                    vertex:wgpu::VertexState{module:&shader,entry_point:Some(vertex),compilation_options:Default::default(),buffers:&[Some(wgpu::VertexBufferLayout{array_stride:32,step_mode:wgpu::VertexStepMode::Vertex,attributes:&wgpu::vertex_attr_array![0=>Float32x3,1=>Float32x3,2=>Float32x2]})]},
                    fragment:Some(wgpu::FragmentState{module:&shader,entry_point:Some(fragment),compilation_options:Default::default(),targets:&[Some(wgpu::ColorTargetState{format,blend:Some(wgpu::BlendState::PREMULTIPLIED_ALPHA_BLENDING),write_mask:wgpu::ColorWrites::ALL})]}),
                    primitive:wgpu::PrimitiveState{cull_mode:if outline{Some(wgpu::Face::Front)}else{match i%3{1=>Some(wgpu::Face::Front),2=>Some(wgpu::Face::Back),_=>None}},..Default::default()},
                    depth_stencil:Some(wgpu::DepthStencilState{format:wgpu::TextureFormat::Depth32Float,depth_write_enabled:Some(i<6 || i==9),depth_compare:Some(wgpu::CompareFunction::LessEqual),stencil:Default::default(),bias:Default::default()}),
                    multisample:Default::default(),multiview_mask:None,cache:None,
                })
            }).collect()
        };
        let draws = model
            .primitives
            .iter()
            .map(|p| Draw {
                vertex: device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                    label: Some("vrm.skinned-vertices"),
                    contents: bytemuck::cast_slice(&p.vertices),
                    usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
                }),
                index: device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                    label: Some("vrm.indices"),
                    contents: bytemuck::cast_slice(&p.indices),
                    usage: wgpu::BufferUsages::INDEX,
                }),
                count: p.indices.len() as u32,
                material: p.material,
                depth: average_depth(p),
            })
            .collect();
        Self {
            draws,
            materials,
            camera,
            camera_group,
            pipelines: make_pipelines(format),
            capture_pipelines: make_pipelines(wgpu::TextureFormat::Rgba8Unorm),
            depth: RefCell::new(None),
        }
    }
    pub fn update(&mut self, gpu: &Gpu, model: &VrmModel) {
        gpu.queue
            .write_buffer(&self.camera, 64, bytemuck::bytes_of(&model.elapsed()));
        for (draw, p) in self.draws.iter_mut().zip(&model.primitives) {
            gpu.queue
                .write_buffer(&draw.vertex, 0, bytemuck::cast_slice(&p.vertices));
            draw.depth = average_depth(p);
        }
    }
    pub fn set_matrix(&self, gpu: &Gpu, matrix: Matrix44) {
        gpu.queue
            .write_buffer(&self.camera, 0, bytemuck::cast_slice(matrix.as_slice()));
    }
    pub fn count(&self) -> usize {
        self.draws.len()
    }
    pub fn encode(
        &self,
        gpu: &Gpu,
        encoder: &mut wgpu::CommandEncoder,
        view: &wgpu::TextureView,
        width: u32,
        height: u32,
        capture: bool,
    ) {
        gpu.queue.write_buffer(
            &self.camera,
            68,
            bytemuck::cast_slice(&[width as f32, height as f32]),
        );
        let mut depth = self.depth.borrow_mut();
        if depth.as_ref().is_none_or(|d| d.0 != width || d.1 != height) {
            let texture = gpu.device.create_texture(&wgpu::TextureDescriptor {
                label: Some("vrm.depth"),
                size: wgpu::Extent3d {
                    width,
                    height,
                    depth_or_array_layers: 1,
                },
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format: wgpu::TextureFormat::Depth32Float,
                usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
                view_formats: &[],
            });
            *depth = Some((width, height, texture.create_view(&Default::default())));
        }
        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("vrm.depth-pass"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view,
                depth_slice: None,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Clear(wgpu::Color::TRANSPARENT),
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                view: &depth.as_ref().unwrap().2,
                depth_ops: Some(wgpu::Operations {
                    load: wgpu::LoadOp::Clear(1.),
                    store: wgpu::StoreOp::Store,
                }),
                stencil_ops: None,
            }),
            timestamp_writes: None,
            occlusion_query_set: None,
            multiview_mask: None,
        });
        let pipelines = if capture {
            &self.capture_pipelines
        } else {
            &self.pipelines
        };
        pass.set_bind_group(0, &self.camera_group, &[]);
        let mut order: Vec<_> = (0..self.draws.len()).collect();
        order.sort_by(|&a, &b| {
            let a = &self.draws[a];
            let b = &self.draws[b];
            self.materials[a.material]
                .queue
                .cmp(&self.materials[b.material].queue)
                .then_with(|| b.depth.total_cmp(&a.depth))
        });
        for i in order {
            let draw = &self.draws[i];
            let material = &self.materials[draw.material];
            pass.set_bind_group(1, &material.group, &[]);
            pass.set_vertex_buffer(0, draw.vertex.slice(..));
            pass.set_index_buffer(draw.index.slice(..), wgpu::IndexFormat::Uint32);
            if material.outline {
                pass.set_pipeline(&pipelines[if material.depth_write { 9 } else { 10 }]);
                pass.draw_indexed(0..draw.count, 0, 0..1);
            }
            let kind = if !material.transparent {
                0
            } else if material.depth_write {
                1
            } else {
                2
            };
            pass.set_pipeline(&pipelines[kind * 3 + material.cull as usize]);
            pass.draw_indexed(0..draw.count, 0, 0..1);
        }
    }
}
fn average_depth(p: &pet_vrm::Primitive) -> f32 {
    p.vertices.iter().map(|v| v.position[2]).sum::<f32>() / p.vertices.len().max(1) as f32
}
fn upload_texture(gpu: &Gpu, width: u32, height: u32, rgba: &[u8]) -> wgpu::TextureView {
    let texture = gpu.device.create_texture(&wgpu::TextureDescriptor {
        label: Some("vrm.texture"),
        size: wgpu::Extent3d {
            width,
            height,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: wgpu::TextureFormat::Rgba8Unorm,
        usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
        view_formats: &[],
    });
    gpu.queue.write_texture(
        texture.as_image_copy(),
        rgba,
        wgpu::TexelCopyBufferLayout {
            offset: 0,
            bytes_per_row: Some(width * 4),
            rows_per_image: Some(height),
        },
        texture.size(),
    );
    texture.create_view(&Default::default())
}
