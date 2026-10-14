#!/usr/bin/env python3
"""Prepare local source trees for a native GBA-link multiplayer proof of concept.

This makes guarded, repeatable source edits only. It does not read, modify, or
distribute a ROM. After running it, rebuild the local pokeemerald decompilation,
then use prepare_native_link_patches.ps1 to make separate host/join test ROMs.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SIO_MARKER = "/* CUBHMA_NATIVE_LINK_MODE_PATCH */"
BUILD_MARKER = "# CUBHMA_NATIVE_SIO_ROLE_PATCH"
LOADER_MARKER = "CUBHMA_NATIVE_BOOTSTRAP_ENABLED"

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
    /* In a direct two-console cable session, this ROM generates the clock. */
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
     * With a direct two-console cable, master receives the slave in slot 1;
     * slave receives the master in slot 0. The existing adapter role still
     * receives slot 0, as its external adapter is the master. */
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

OLD_LOADER_BLOCK = """    /*
     * Leave the live IRQ vector alone at boot. The mGBA client script detects
     * whether it has injected the payload by checking that vector; if it were
     * already pointing into this payload, the script would skip startup and
     * never establish the local network bridge. The script will overwrite
     * this reserved EWRAM region and install the hook after entering the
     * overworld.
     */
}"""
NEW_LOADER_BLOCK = """    /*
     * CUBHMA_NATIVE_BOOTSTRAP_ENABLED
     * Native ROM-resident mode: AgbMain has initialized the game before calling
     * this loader. Install the IRQ hook only after the payload and its original
     * handler pointer have been copied and checked.
     */
    *CUBHMA_IRQ_VECTOR = CUBHMA_PAYLOAD_EWRAM_BASE;
}"""


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise ValueError(f"Expected exactly one {label} anchor; found {n}.")
    return text.replace(old, new, 1)


def transform_sio(text: str) -> tuple[str, bool]:
    if SIO_MARKER in text:
        if all(s in text for s in (
            "REG_SIOMULTI1", "SioRxWord(REG_SIOMULTI1)",
            "PAYLOAD_NATIVE_SIO_MASTER", "REG_SIOCNT |= SIOCNT_START",
        )):
            return text, False
        raise ValueError("payload/sio.c has a partial native-SIO patch; inspect it manually.")
    text = replace_once(text, OLD_REGS, NEW_REGS, "serial register declaration")
    text = replace_once(text, OLD_ARM, NEW_ARM, "SioArm")
    text = replace_once(text, OLD_RX, NEW_RX, "SioOnSerialIrq receive/transmit block")
    return text, True


def transform_build(text: str) -> tuple[str, bool]:
    if BUILD_MARKER in text:
        if all(s in text for s in (
            "$NativeSioRole", "@sioRoleDefs", "-DPAYLOAD_NATIVE_SIO_MASTER",
        )):
            return text, False
        raise ValueError("build.ps1 has a partial native-SIO role patch; inspect it manually.")

    param_anchor = """    [switch]$WithSio,
"""
    param_insert = """    [switch]$WithSio,

    # CUBHMA_NATIVE_SIO_ROLE_PATCH
    # For native two-console tests: master clocks transfers; slave responds.
    # The default adapter role preserves the original physical-adapter build.
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
    return text, True


def transform_loader(text: str) -> tuple[str, bool]:
    if LOADER_MARKER in text:
        if "*CUBHMA_IRQ_VECTOR = CUBHMA_PAYLOAD_EWRAM_BASE;" in text:
            return text, False
        raise ValueError("Loader has a partial native bootstrap patch; inspect it manually.")
    text = replace_once(text, OLD_LOADER_BLOCK, NEW_LOADER_BLOCK, "payload loader tail")
    return text, True


def write_with_backup(path: Path, new_text: str) -> None:
    backup = Path(str(path) + ".pre-native-link.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(new_text, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submodule-root", required=True, type=Path,
                        help="Path to third_party/gen3-poke-multiplayer.")
    parser.add_argument("--pokeemerald-root", required=True, type=Path,
                        help="Path to the integrated local pret/pokeemerald checkout.")
    args = parser.parse_args()

    subroot = args.submodule_root.resolve()
    game = args.pokeemerald_root.resolve()
    paths = {
        "sio": subroot / "payload" / "sio.c",
        "build": subroot / "build.ps1",
        "loader": game / "src" / "cubhma_multiplayer_payload.c",
    }
    for name, path in paths.items():
        if not path.is_file():
            print(f"error: {name} source not found: {path}", file=sys.stderr)
            return 1

    try:
        new_sio, sio_changed = transform_sio(paths["sio"].read_text(encoding="utf-8"))
        new_build, build_changed = transform_build(paths["build"].read_text(encoding="utf-8"))
        new_loader, loader_changed = transform_loader(paths["loader"].read_text(encoding="utf-8"))

        updates = (
            ("sio", new_sio, sio_changed),
            ("build", new_build, build_changed),
            ("loader", new_loader, loader_changed),
        )
        # Validate every anchor before writing any file. Backups are never overwritten.
        for name, new_text, changed in updates:
            if changed:
                write_with_backup(paths[name], new_text)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Native-link source preparation complete:")
    print(f"  payload/sio.c: {'patched' if sio_changed else 'already patched'}")
    print(f"  build.ps1:     {'patched' if build_changed else 'already patched'}")
    print(f"  game loader:   {'patched' if loader_changed else 'already patched'}")
    print("Backups use the suffix .pre-native-link.bak.")
    print("Now rebuild pokeemerald.gba before making host/join ROMs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
