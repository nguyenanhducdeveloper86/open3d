# Releasing

Push a version tag to run the signed release workflow:

```bash
git tag v0.1.0-alpha.1
git push origin v0.1.0-alpha.1
```

The workflow builds the Python wheel/sdist and viewer bundle, emits `SHA256SUMS` and a CycloneDX SBOM, then attaches GitHub OIDC build-provenance attestations to every release artifact. Verify a downloaded artifact from the directory containing the assets with `sha256sum -c SHA256SUMS` and inspect attestations on the GitHub release page.

Before tagging, run the test suite, the web build, and the security/license checklist. Do not commit model weights, credentials, private assets, or `.open3d/objects`.
