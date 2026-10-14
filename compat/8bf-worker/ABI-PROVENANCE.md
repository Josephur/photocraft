# Independent Filter Foundry binary ABI observations

This records numeric interoperability observations from GPL binaries, not copied declarations. SDK headers were not fetched or read. See abi-observations.json and local disassembly for evidence.

| Field | x86 offset | x64 offset | Width/type |
|---|---:|---:|---|
| abortProc | 0x4 | 0x4 | pointer |
| progressProc | 0x8 | 0xc | pointer |
| parameters | 0xc | 0x14 | pointer |
| imageSize | 0x10 | 0x1c | v,h i16 |
| planes | 0x14 | 0x20 | i16 |
| filterRect | 0x16 | 0x22 | top,left,bottom,right i16 |
| maxSpace | 0x2c | 0x38 | i32 |
| inRect | 0x34 | 0x40 | four i16 |
| inLoPlane | 0x3c | 0x48 | i16 |
| inHiPlane | 0x3e | 0x4a | i16 |
| outRect | 0x40 | 0x4c | four i16 |
| outLoPlane | 0x48 | 0x54 | i16 |
| outHiPlane | 0x4a | 0x56 | i16 |
| inData | 0x4c | 0x58 | pointer |
| inRowBytes | 0x50 | 0x60 | i32 |
| outData | 0x54 | 0x64 | pointer |
| outRowBytes | 0x58 | 0x6c | i32 |
| maskRect | 0x60 | 0x74 | four i16 |
| hostSig | 0x78 | 0x90 | u32 |
| imageMode | 0x80 | 0x9c | i16 |
| platformData | 0xbc | 0xd8 | pointer |
| bufferProcs | 0xc0 | 0xe0 | pointer |
| displayPixels | 0xcc | 0xf8 | pointer |
| handleProcs | 0xd0 | 0x100 | pointer |
| advanceState | 0xe0 | 0x118 | pointer |
| propertyProcs | 0x140 | 0x188 | pointer |
| sSPBasic | 0x174 | 0x1d0 | pointer |
| depth | 0x17c | 0x1e0 | i32 |
| bigDocumentData | 0x190 | 0x1f8 | pointer |
| maxSpace64 | 0x1b0 | 0x228 | i64 |

PlatformData HWND and AboutRecord platform pointer are at offset zero. x86 entry and examined callbacks use cdecl; x64 uses Windows x64 ABI.

Canonical legacy-table version numbers, bufferSpace, maskData/maskRowBytes, and complete record size have not been independently established.

Resources and disassembly remain local research evidence. This does not establish broad commercial-filter compatibility.

## Reproduction sources and implementation boundary

The samples were Filter Foundry 1.7.0.25 from https://github.com/danielmarschall/filter_foundry/releases/tag/1.7.0.25 (GPL). The JSON records their hashes and machine-code evidence addresses. No Filter Foundry code is compiled, linked or redistributed by this project; the Rust implementation and test DLL are original. Only interoperable binary facts are recorded. The sample DLLs and disassembly remain local test/research inputs.

PSFilterPdn (https://github.com/0xC0000054/PSFilterPdn) and gimp-pspi (https://github.com/draekko/gimp-pspi) supplied architectural context. SDK-adapted ABI declarations discovered in these references were excluded. PhotoCraft requires no Adobe SDK, header, library, application or runtime. PiPL resource framing was independently checked against GPL sample resources and Nicholas Hayes's author-written MIT scanner implementation.

The version words offered by our legacy callback tables are compatibility choices, validated with the tested filters; they are not claimed as reconstructed canonical constants. The 4096-byte zero-filled record is a bounded compatibility envelope, not a claim about the complete interface size. Optional services remain absent. Unsupported or crashing native modules are reported to the editor as failed jobs.

Vicanek test downloads were used locally under their supplied usage license. They are not part of this repository and were not disassembled or redistributed.
