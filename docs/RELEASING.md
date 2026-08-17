# Releasing

Before an alpha tag:

1. run the standard-library tests and the example clean-room workflow;
2. run the security and license checklist;
3. verify no model weights, credentials, generated private assets, or `.open3d/objects` are tracked;
4. publish checksums and a dependency/license inventory for any optional adapter;
5. describe known limitations instead of calling unsupported adapters production-ready.

Signed installers, SBOM, provenance attestations, and an updater belong to the desktop release track. They are not faked by this source-only core repository.
