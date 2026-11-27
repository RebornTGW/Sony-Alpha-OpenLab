# target-helper - Open Gate on-camera micro-helper (clean-room MIT).
#
# Primary target: a minimal aarch64 .so for Sony CE Linux 4.9 (BIONZ XR),
# freestanding, no external deps. Plus a host self-test built with the native cc.

CROSS   ?= aarch64-linux-gnu-
CC      := $(CROSS)gcc
HOSTCC  ?= cc

INC     := -Iinclude
# Freestanding, position-independent, no libc; tiny and self-contained.
CFLAGS  := -std=c99 -Os -ffreestanding -fPIC -fno-stack-protector \
           -fno-builtin -fvisibility=hidden -Wall -Wextra $(INC)
LDFLAGS := -shared -nostdlib -Wl,--build-id=none -Wl,-z,noexecstack

SRC     := src/helper.c
OUT     := build

.PHONY: all so test clean

all: so

# aarch64 shared object (the on-camera helper)
so: $(OUT)/libogpatch.so

$(OUT)/libogpatch.so: $(SRC) include/ogpatch.h
	@mkdir -p $(OUT)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(SRC)
	@echo "built $@ (aarch64; verify: $(CROSS)readelf -hd $@)"

# host logic self-test (native compiler, no aarch64 needed)
test: $(OUT)/test_helper
	$(OUT)/test_helper

$(OUT)/test_helper: test/test_helper.c $(SRC) include/ogpatch.h
	@mkdir -p $(OUT)
	$(HOSTCC) -std=c99 -Wall -Wextra $(INC) -o $@ test/test_helper.c $(SRC)

clean:
	rm -rf $(OUT)
