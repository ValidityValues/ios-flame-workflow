# Full Build workflow

The **Full Build - Pixel 4** workflow calls the existing XNU build, then compiles the in-repository iOS-on-phone components and creates a shim boot image in the same run.

## Run it

1. Open Actions -> Full Build - Pixel 4 -> Run workflow.
2. Keep DEVELOPMENT selected unless you need another kernel configuration.
3. Start the run and let both jobs complete.
4. Download the ios-flame-full-build artifact. Verify the files with the SHA256SUMS file included inside it.

The artifact contains the raw kernel, flame-boot.img, generated ADT, Wi-Fi/GPU tools, on-phone utilities, Metal and Metal 2 bundles, Turnip and FlameBridge for macOS. The pinned Mesa, UniXNU, metal2vulkan, mkbootimg and avbtool revisions are recorded in build-info.txt.

## Important limits

A boot image is not an installed iOS system. The iOS HFS+ root volume is several gigabytes of Apple's proprietary userland; it must be prepared from the iPhone X iOS 16.7.16 (20H392) IPSW and installed to Pixel 4 userdata as documented in the repository README. It is not uploaded in this public workflow artifact. The workflow also excludes Google's full factory archive, Qualcomm firmware dumps and personal modem/calibration backups. As a result, the boot image does not include GPU firmware. Metal 2 and Turnip are compiled and included, but hardware acceleration requires firmware extracted locally from the user's own official Pixel 4 factory image.

The workflow never flashes the phone. After the HFS+ root is installed and the local firmware/ADT step is complete, use fastboot boot boot/flame-boot.img for temporary boot testing. Do not flash or relock the bootloader on modified software.
