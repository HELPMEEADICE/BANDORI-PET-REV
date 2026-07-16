# Native release operations

`Native CI` builds and packages the Rust + LuaJIT + Qt application on Windows,
macOS and Linux for every migration-branch push and pull request. Each runner
installs the CPack staging tree, runs `BandoriPet --help` with the offscreen Qt
platform, validates required resources and confirms that no Python runtime was
installed. It then verifies the platform package container and uploads packages
with a `SHA256SUMS` file.

`Native Release` runs for `v*` tags or manual dispatch. A tag must match the root
`VERSION` exactly. Tag releases require signing credentials; a missing credential
fails the corresponding job before a release can be published. Manual dispatch
allows an unsigned packaging dry run unless `require_signing` is selected.

## Repository secrets

Windows Authenticode uses:

- `WINDOWS_SIGNING_CERTIFICATE_BASE64`: base64-encoded PFX certificate.
- `WINDOWS_SIGNING_CERTIFICATE_PASSWORD`: PFX password.

macOS signing and notarization use:

- `MACOS_SIGNING_CERTIFICATE_BASE64`: base64-encoded Developer ID P12.
- `MACOS_SIGNING_CERTIFICATE_PASSWORD`: P12 password.
- `MACOS_SIGNING_IDENTITY`: complete Developer ID Application identity.
- `APPLE_ID`: notarization Apple ID.
- `APPLE_TEAM_ID`: Apple Developer team ID.
- `APPLE_APP_PASSWORD`: app-specific password accepted by `notarytool`.

The workflow imports credentials into runner-temporary files/keychains. CPack
signs installed Windows binaries or the complete macOS application bundle before
forming the package. The Windows NSIS installer is signed after CPack. The macOS
DMG is submitted with `notarytool`, stapled and validated. GitHub also records a
Sigstore-backed provenance attestation for every release package.

## Release sequence

1. Merge a green `Native CI` run on all three runners.
2. Update `VERSION` and release notes, then push the commit.
3. Create and push the matching tag, for example `v3.1.4`.
4. Confirm that all three signed package jobs and the publish job succeed.
5. Verify a downloaded asset with `gh attestation verify <asset> --repo <owner/repo>`
   and the matching entry in `SHA256SUMS`.

Unsigned artifacts from ordinary CI or manual dry runs are validation outputs,
not end-user releases.
