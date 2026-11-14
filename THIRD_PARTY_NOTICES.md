# Third-party notices and asset scope

The tool code in this repository is distributed under the MIT license. This is an independent project; game names identify the supported product.

## Public source

The source package contains the Python application, browser UI, Tauri 2 desktop shell, C++ adapter, scripts and interface metadata. It excludes original game binaries, machine-code comparison tables, initial PKM inputs and input snapshots.

## Desktop release

The v1103.2, v1106 and v1108.5 EXEs are separate desktop distributions. Each includes a private CPython 3.12 runtime and its `LICENSE.txt`, the tool's native host, compatibility comparison data and matching initial inputs. It loads the original engine DLL and game resource archives from the user's installation; those game components are not included in the EXE.

The MIT grant covers the tool code. It does not relicense game-related inputs, extracted comparison bytes, third-party components or their trademarks. CPython and its bundled components retain the licenses shipped in the runtime. Windows SDK and MSVC are build prerequisites and are not included in the source archive.

Save import uses fmsave 0.12.4 (MIT) and backports.zstd 1.8.0 (PSF-2.0 with the bundled Zstandard license). The public source lists these packages as dependencies. Desktop builds include the packages and their license files.

## Fonts

Barlow and Barlow Condensed are distributed under the SIL Open Font License 1.1, copyright the Barlow Project Authors. JetBrains Mono is distributed under the SIL Open Font License 1.1, copyright JetBrains s.r.o. The woff2 files are self-hosted through the @fontsource packages; their license files are retained in the desktop resources and are not relicensed by this project.
