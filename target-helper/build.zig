// build.zig - build the Open Gate micro-helper with Zig (bundled cc).
// Written for Zig 0.17.1 (module-based API: addLibrary + createModule).
//
//   zig build        -> zig-out/lib/libogpatch.so   (freestanding aarch64-linux)
//   zig build test   -> builds + runs test/test_helper.c on the host
const std = @import("std");

pub fn build(b: *std.Build) void {
    const optimize: std.builtin.OptimizeMode = .ReleaseSmall;

    // ---- the on-camera helper: freestanding aarch64-linux-gnu shared object ----
    const target = b.resolveTargetQuery(.{
        .cpu_arch = .aarch64,
        .os_tag = .linux,
        .abi = .gnu,
    });

    const mod = b.createModule(.{
        .target = target,
        .optimize = optimize,
        .link_libc = false, // freestanding: no libc
        .pic = true,
    });
    mod.addIncludePath(b.path("include"));
    mod.addCSourceFile(.{
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

    const lib = b.addLibrary(.{
        .linkage = .dynamic,
        .name = "ogpatch",
        .root_module = mod,
    });
    b.installArtifact(lib);

    // ---- host self-test: builds test/test_helper.c + src/helper.c natively ----
    const test_mod = b.createModule(.{
        .target = b.resolveTargetQuery(.{}), // native host
        .optimize = optimize,
        .link_libc = true,
    });
    test_mod.addIncludePath(b.path("include"));
    test_mod.addCSourceFiles(.{
        .files = &.{ "test/test_helper.c", "src/helper.c" },
        .flags = &.{ "-std=c99", "-Wall", "-Wextra" },
    });

    const test_exe = b.addExecutable(.{
        .name = "test_helper",
        .root_module = test_mod,
    });
    const run_test = b.addRunArtifact(test_exe);
    const test_step = b.step("test", "build and run the helper self-test");
    test_step.dependOn(&run_test.step);
}
