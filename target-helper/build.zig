// build.zig - build the Open Gate micro-helper with Zig as a cross cc.
// Tested shape for Zig 0.13 / 0.14. Zig bundles the aarch64 toolchain, so no
// external cross-gcc is needed:  zig build
//
// Outputs a freestanding aarch64-linux .so into zig-out/lib/.
const std = @import("std");

pub fn build(b: *std.Build) void {
    // Fixed target: Sony CE Linux 4.9 on BIONZ XR (aarch64-linux-gnu).
    const target = b.resolveTargetQuery(.{
        .cpu_arch = .aarch64,
        .os_tag = .linux,
        .abi = .gnu,
    });
    const optimize: std.builtin.OptimizeMode = .ReleaseSmall;

    const lib = b.addSharedLibrary(.{
        .name = "ogpatch",
        .target = target,
        .optimize = optimize,
    });
    lib.addIncludePath(b.path("include"));
    lib.addCSourceFile(.{
        .file = b.path("src/helper.c"),
        .flags = &.{
            "-std=c99",
            "-ffreestanding",
            "-fno-stack-protector",
            "-fno-builtin",
            "-fvisibility=hidden",
            "-Wall",
            "-Wextra",
        },
    });
    // Freestanding: do not link libc.
    lib.linkage = .dynamic;
    b.installArtifact(lib);
}
