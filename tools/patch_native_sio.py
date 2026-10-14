#!/usr/bin/env python3
"""Patch the pinned Gen 3 multiplayer payload for native two-GBA SIO testing.

This applies small, guarded edits to the user's local submodule checkout. It does
not touch a ROM. The generated payload has a compile-time master or slave role so
two ROM instances can prove that native in-game serial I/O works before adding
the host/join menu.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SIO_MARKER = "/* CUBHMA_NATIVE_LINK_MODE_PATCH */"
BUILD_MARKER = "# CUBHMA_NATIVE_SIO_ROLE_PATCH"

OLD_REGS = """#define REG_SIOMULTI0   (*(volatile u16 *)0x04000120)
#define REG_RCNT"""
NEW_REGS = """#define REG_SIOMULTI0   (*(volatile u16 *)0x04000120)
#define REG_SIOMULTI1   (*(volatile u16 *)0x04000122)
/* CUBHMA_NATIVE_LINK_MODE_PATCH */
#define REG_RCNT"""

OLD_ARM = """static __attribute__((noinline)) void SioArm(void)
{
    REG_RCNT   = RCNT_SIO_MODE;
    REG_SIOCNT = SIOCNT_MULTI | SIOCNT_BAUD_115200 | SIOCNT_IRQ;
    REG_IE    |= IRQ_SERIAL;
    sSio.rxPhase = RX_WAIT_SYNC;
    REG_SIOMLT_SEND = SioPeekWord();
}"""

NEW_ARM = """static __attribute__((noinline)) void SioArm(void)
{
    REG_RCNT   = RCNT_SIO_MODE;
    REG_SIOCNT = SIOCNT_MULTI | SIOCNT_BAUD_115200 | SIOCNT_IRQ;
    REG_IE    |= IRQ_SERIAL;
    sSio.rxPhase = RX_WAIT_SYNC;
    REG_SIOMLT_SEND = SioPeekWord();
#if defined(PAYLOAD_NATIVE_SIO_MASTER)
    /* In a normal GBA cable session, one console must generate the clock. */
    REG_SIOCNT |= SIOCNT_START;
#endif
}"""

OLD_RX = """    /* In Multi-Player il master finisce nel proprio slot e i child a seguire.
     * L'adattatore e' il master, quindi la sua parola sta in SIOMULTI0. */
    SioRxWord(REG_SIOMULTI0);

    /* Carichiamo subito la prossima parola: il master puo' ripartire appena
     * vuole, e trovare il registro gia' pronto evita di perdere uno scambio. */
    REG_SIOMLT_SEND = SioNextWord();

    REG_IF = IRQ_SERIAL;"""

NEW_RX = """    /* CUBHMA_NATIVE_LINK_MODE_PATCH
     * With a direct two-console cable, the master receives the slave in slot 1;
     * the slave receives the master in slot 0. In the original adapter build,
     * the external adapter is master, so the existing slot-0 path is retained. */
#if defined(PAYLOAD_NATIVE_SIO_MASTER)
    SioRxWord(REG_SIOMULTI1);
#else
    SioRxWord(REG_SIOMULTI0);
#endif

    /* Prepare the next outgoing word before the master starts another transfer. */
    REG_SIOMLT_SEND = SioNextWord();
#if defined(PAYLOAD_NATIVE_SIO_MASTER)
    REG_SIOCNT |= SIOCNT_START;
#endif

    REG_IF = IRQ_SERIAL;"""

def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise ValueError(f"Expected exactly one {label} anchor; found {n}.")
    return text.replace(old, new, 1)


def patch_sio(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if SIO_MARKER in text:
        if "REG_SIOMULTI1" not in text or "SioRxWord(REG_SIOMULTI1)" not in text:
            raise ValueError(f"{path} has a partial native-SIO patch; inspect it manually.")
        return False

    text = replace_once(text, OLD_REGS, NEW_REGS, "serial register declaration")
    text = replace_once(text, OLD_ARM, NEW_ARM, "SioArm")
    text = replace_once(text, OLD_RX, NEW_RX, "SioOnSerialIrq receive/transmit block")
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


def patch_build(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if BUILD_MARKER in text:
        if "$NativeSioRole" not in text or "@sioRoleDefs" not in text:
            raise ValueError(f"{path} has a partial native-SIO build patch; inspect it manually.")
        return False

    param_anchor = """    [switch]$WithSio,
"""
    param_insert = """    [switch]$WithSio,

    # CUBHMA_NATIVE_SIO_ROLE_PATCH
    # For ROM-resident two-console tests: adapter (existing hardware adapter),
    # master (this ROM clocks transfers), or slave (this ROM follows the master).
    [ValidateSet("adapter", "master", "slave")]
    [string]$NativeSioRole = "adapter",
"""
    text = replace_once(text, param_anchor, param_insert, "WithSio parameter")

    error_anchor = '$ErrorActionPreference = "Stop"\n'
    error_insert = '''$ErrorActionPreference = "Stop"

if ($NativeSioRole -ne "adapter" -and -not $WithSio) {
    throw "-NativeSioRole master/slave requires -WithSio."
}
'''
    text = replace_once(text, error_anchor, error_insert, "PowerShell error handling anchor")

    defs_anchor = """$mainDefs = @()
if ($WithSio) { $mainDefs += "-DPAYLOAD_WITH_SIO" }
"""
    defs_insert = """$mainDefs = @()
if ($WithSio) { $mainDefs += "-DPAYLOAD_WITH_SIO" }

$sioRoleDefs = @()
if ($NativeSioRole -eq "master") {
    $sioRoleDefs += "-DPAYLOAD_NATIVE_SIO_MASTER"
} elseif ($NativeSioRole -eq "slave") {
    $sioRoleDefs += "-DPAYLOAD_NATIVE_SIO_SLAVE"
}
'''
    text = replace_once(text, defs_anchor, defs_insert, "compiler defines block")

    compile_anchor = '& $gcc @common -Os -fno-jump-tables -fno-guess-branch-probability -fno-move-loop-invariants @stackFlags @noInterwork -mthumb -c (Join-Path $root "payload\\sio.c") -o (Join-Path $build "sio.o")'
    compile_insert = '& $gcc @common -Os -fno-jump-tables -fno-guess-branch-probability -fno-move-loop-invariants @stackFlags @sioRoleDefs @noInterwork -mthumb -c (Join-Path $root "payload\\sio.c") -o (Join-Path $build "sio.o")'
    text = replace_once(text, compile_anchor, compile_insert, "sio.c compile command")
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submodule-root", required=True, type=Path,
                        help="Path to third_party/gen3-poke-multiplayer.")
    args = parser.parse_args()
    root = args.submodule_root.resolve()
    sio = root / "payload" / "sio.c"
    build = root / "build.ps1"
    if not sio.is_file() or not build.is_file():
        print(f"error: {root} does not contain payload/sio.c and build.ps1.", file=sys.stderr)
        return 1
    try:
        sio_changed = patch_sio(sio)
        build_changed = patch_build(build)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("Native two-console SIO mode is ready.")
    print(f"  payload/sio.c: {'patched' if sio_changed else 'already patched'}")
    print(f"  build.ps1:     {'patched' if build_changed else 'already patched'}")
    print("Use -WithSio -NativeSioRole master for host ROM and slave for join ROM.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
