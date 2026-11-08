# VRM third-party notices

Natural idle comes from pixiv/ChatVRM, revision
`b542aa00e19dccf9fc48ba340cf7eee011d2329a`, `public/idle_loop.vrma`:
https://github.com/pixiv/ChatVRM/blob/b542aa00e19dccf9fc48ba340cf7eee011d2329a/public/idle_loop.vrma

SHA-256 (`idle-natural.vrma`):
`ace95ba6dcc0bdf2ed1081c002332b4184441117c8d543b6f642b3d2c5cf99be`.
The repository's MIT notice is retained in `ChatVRM-LICENSE.txt`.

Interaction motions come from tk256ailab/vrm-viewer, revision
`0cd2267f36939da589afc8eac449b5b9ccce4c01`, directory `VRMA/`:
https://github.com/tk256ailab/vrm-viewer/tree/0cd2267f36939da589afc8eac449b5b9ccce4c01/VRMA

| Bundled file | Original | SHA-256 |
|---|---|---|
| wave.vrma | Goodbye.vrma | `6a162b83a0b9b8c1d6ee5c05adf71ccb16f012286bab1dd3b1d69f5a1d3c9fbe` |
| look-around.vrma | LookAround.vrma | `cf5c51bf07845b29c8f664cea6cf694f05f0d51fbf41a716414b656db72e411f` |
| thinking.vrma | Thinking.vrma | `0c52edd6e97bd6da23ac1f6c386b6c51bead3be4193c01ca08b39696fb3944f5` |
| relax.vrma | Relax.vrma | `7de5b0a0e8099d0fa2b6dbdb9e04ee490a77543aa6b1be35bada146bdf43f289` |
| blush.vrma | Blush.vrma | `9057f93fe8add98c781955ebc0df686bec79dbb90cc6351b092a3a4fea8e8edf` |

The repository's MIT notice is retained in `vrm-viewer-LICENSE.txt`.
These motion bytes are unmodified; runtime playback adds retargeting, source-unit
conversion, in-place root offsets, a loop overlap, speed controls and crossfades.
No VRM model from either repository is included. Assets are embedded in the
native executable and do not require runtime network access.

Native MToon and spring-bone math reference the VRM specifications and UniVRM:

- https://github.com/vrm-c/vrm-specification/tree/master/specification/VRMC_materials_mtoon-1.0
- https://github.com/vrm-c/UniVRM/blob/master/Packages/VRM/MToon/Shaders/MToonCore.cginc
- https://github.com/pixiv/three-vrm/tree/dev/packages/three-vrm-springbone

UniVRM/MToon's MIT notice is retained in `UniVRM-LICENSE.txt`.
The WGSL implementation is native to this project; Unity is not a runtime
dependency. Notices are copied into `licenses/vrm/` by the application packager.

The tiny VRM fixtures in `../tests/fixtures/` are original generated test meshes;
their generator is included. User-provided POPY files are not part of the source
or release package.
