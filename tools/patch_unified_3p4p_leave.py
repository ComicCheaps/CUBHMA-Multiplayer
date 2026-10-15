#!/usr/bin/env python3
"""Enable all three remote slots over native GBA multi-SIO and add Disconnect.

Run from the CUBHMA-Multiplayer checkout after the existing unified-role,
compact-lobby, and Start-menu request patches:
  python .\tools\patch_unified_3p4p_leave.py

Then rebuild pokeemerald in WSL and run prepare_unified_native_link_rom.ps1.
This source transformation is intentionally guarded and writes backups.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

MARKER = "CUBHMA_UNIFIED_3P4P_PER_PEER_RX"
SIO_MARKER = "CUBHMA_UNIFIED_3P4P_PER_PEER_RX_SIO"
ROOT = Path(__file__).resolve().parent.parent
SUBMODULE = ROOT / "third_party" / "gen3-poke-multiplayer"


def once(source: str, old: str, new: str, label: str) -> str:
    n = source.count(old)
    if n != 1:
        raise ValueError(f"Expected exactly one {label} anchor; found {n}.")
    return source.replace(old, new, 1)


def replace_function(source: str, name: str, replacement: str, label: str) -> str:
    pattern = rf"(?:static )?[^\n]+\b{name}\(void\)\s*\{{.*?^\}}"
    updated, n = re.subn(pattern, lambda _: replacement, source, count=1, flags=re.S | re.M)
    if n != 1:
        raise ValueError(f"Could not uniquely replace {label} (matches={n}).")
    return updated


def patch_sio(source: str) -> tuple[str, bool]:
    if SIO_MARKER in source:
        return source, False
    if "CUBHMA_UNIFIED_RUNTIME_ROLE" not in source or "CUBHMA_UNIFIED_LINK_ID_MASTER" not in source:
        raise ValueError("Apply the unified runtime-role and Start-menu helper patches first.")

    source = once(
        source,
        "#define REG_SIOMULTI0   (*(volatile u16 *)0x04000120)\n",
        "#define REG_SIOMULTI0   (*(volatile u16 *)0x04000120)\n"
        "#define REG_SIOMULTI(n) (*(volatile u16 *)(0x04000120u + 2u * (u32)(n)))\n",
        "SIO multi-register accessor",
    )

    old_struct = re.search(r"struct SioState\s*\{.*?^\};", source, re.S | re.M)
    if not old_struct:
        raise ValueError("Could not find the native SIO state structure.")
    new_struct = r'''struct SioRxState {
    u8  rxPhase;
    u8  rxType;
    u8  rxCount;
    u8  rxGot;
    u16 rxSum;
    u16 rxBuf[SIO_MAX_WORDS];
};

struct SioState {
    u8 active;
    /* One framing state per remote GBA ID. The peers transmit independent
     * word streams during the same multiplayer transfers. */
    struct SioRxState rx[4];
    u16 txBuf[SIO_MAX_WORDS + 3];
    u8 txLen;
    u8 txPos;
};'''
    source = source[:old_struct.start()] + new_struct + source[old_struct.end():]

    source = once(
        source,
        "static volatile u8 sNativeRole = CUBHMA_NATIVE_ROLE_OFF;\n",
        "static volatile u8 sNativeRole = CUBHMA_NATIVE_ROLE_OFF;\n"
        "/* Once a session starts, ID 0 keeps clocking even if that player leaves;\n"
        " * otherwise the remaining child windows would lose their clock source. */\n"
        "static volatile u8 sNativeTransportStarted;\n"
        "u8 SioGetDeviceId(void);\n",
        "runtime transport latch",
    )
    old_role_fn = r'''void SioSetNativeRole(u8 role)
{
    if (role <= CUBHMA_NATIVE_ROLE_JOIN)
        sNativeRole = role;
}'''
    new_role_fn = r'''void SioSetNativeRole(u8 role)
{
    if (role <= CUBHMA_NATIVE_ROLE_JOIN)
    {
        sNativeRole = role;
        if (role != CUBHMA_NATIVE_ROLE_OFF)
        {
            sNativeTransportStarted = 1;
            if (sSio.active && SioGetDeviceId() == 0u)
                REG_SIOCNT |= SIOCNT_START;
        }
    }
}'''
    source = once(source, old_role_fn, new_role_fn, "runtime role setter")

    role_getter = r'''u8 SioGetNativeRole(void)
{
    return sNativeRole;
}'''
    if source.count(role_getter) != 1:
        raise ValueError("Could not uniquely find SioGetNativeRole.")
    helper_pattern = r"(u8 SioGetNativeRole\(void\)\s*\{\s*return sNativeRole;\s*\}\s*#endif\s*)(static u16 SioPeekWord\(void\);)"
    helper_replacement = r"\1" + (
        "\nu8 SioGetDeviceId(void)\n{\n"
        "    return (u8)((REG_SIOCNT & SIOCNT_ID_MASK) >> 4);\n"
        "}\n\n"
        "int SioTxIdle(void)\n{\n"
        "    return sSio.txLen == 0;\n"
        "}\n\n"
    ) + r"\2"
    source, helper_count = re.subn(
        helper_pattern, helper_replacement, source, count=1, flags=re.S
    )
    if helper_count != 1:
        raise ValueError("Could not insert shared SIO helper functions outside the runtime-only block.")

    arm_fn = r'''static __attribute__((noinline)) void SioArm(void)
{
    u32 i;
    REG_RCNT   = RCNT_SIO_MODE;
    REG_SIOCNT = SIOCNT_MULTI | SIOCNT_BAUD_115200 | SIOCNT_IRQ;
    REG_IE    |= IRQ_SERIAL;
    for (i = 0; i < 4; i++)
        sSio.rx[i].rxPhase = RX_WAIT_SYNC;
    REG_SIOMLT_SEND = SioPeekWord();
#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)
    if (sNativeTransportStarted && SioGetDeviceId() == 0u)
        REG_SIOCNT |= SIOCNT_START;
#elif defined(PAYLOAD_NATIVE_SIO_MASTER)
    REG_SIOCNT |= SIOCNT_START;
#endif
}'''
    source = replace_function(source, "SioArm", arm_fn, "SioArm")

    source = once(
        source,
        "extern int SioDeliverFrame(u8 type, const u16 *words, u8 count);",
        "extern int SioDeliverFrame(u8 sourceId, u8 type, const u16 *words, u8 count);",
        "source-aware frame delivery declaration",
    )

    rx_fn = r'''static void SioRxWord(u8 sourceId, u16 w)
{
    struct SioRxState *rx;
    if (sourceId >= 4u)
        return;
    rx = &sSio.rx[sourceId];
    g_sio.wordsRx++;

    switch (rx->rxPhase) {
    case RX_WAIT_SYNC:
        if (w == SIO_SYNC)
            rx->rxPhase = RX_WAIT_HEAD;
        break;

    case RX_WAIT_HEAD: {
        u8 type = (u8)(w >> 8);
        u8 count = (u8)(w & 0xFF);
        if (count > SIO_MAX_WORDS || type == 0) {
            g_sio.frameErr++;
            g_sio.resync++;
            rx->rxPhase = RX_WAIT_SYNC;
            break;
        }
        rx->rxType = type;
        rx->rxCount = count;
        rx->rxGot = 0;
        rx->rxSum = w;
        rx->rxPhase = count ? RX_DATA : RX_CKSUM;
        break;
    }

    case RX_DATA:
        rx->rxBuf[rx->rxGot++] = w;
        rx->rxSum = (u16)(rx->rxSum + w);
        if (rx->rxGot >= rx->rxCount)
            rx->rxPhase = RX_CKSUM;
        break;

    case RX_CKSUM:
        if ((u16)(rx->rxSum + w) != 0) {
            g_sio.frameErr++;
            g_sio.resync++;
        } else {
            g_sio.framesRx++;
            if (!SioDeliverFrame(sourceId, rx->rxType, rx->rxBuf, rx->rxCount))
                g_sio.rxFull++;
        }
        rx->rxPhase = RX_WAIT_SYNC;
        break;
    }
}'''
    pattern = r"static void SioRxWord\(u16 w\)\s*\{.*?^\}"
    source, n = re.subn(pattern, lambda _: rx_fn, source, count=1, flags=re.S | re.M)
    if n != 1:
        raise ValueError("Could not uniquely replace SioRxWord.")

    irq_fn = r'''void SioOnSerialIrq(void)
{
    u16 cnt;
#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)
    u8 localId;
    u8 peer;
#endif

    if (!sSio.active)
        return;

    g_sio.irqs++;
    cnt = REG_SIOCNT;
    if (cnt & SIOCNT_ERROR)
        g_sio.errFlag++;

#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)
    localId = SioGetDeviceId();
    /* Every transfer carries one word from each of the four devices. Keep
     * the receive phase independently aligned for every other device. */
    for (peer = 0; peer < 4u; peer++)
        if (peer != localId)
            SioRxWord(peer, REG_SIOMULTI(peer));
#else
#if defined(PAYLOAD_NATIVE_SIO_MASTER)
    SioRxWord(1u, REG_SIOMULTI(1u));
#else
    SioRxWord(0u, REG_SIOMULTI(0u));
#endif
#endif

    REG_SIOMLT_SEND = SioNextWord();
#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)
    if (sNativeTransportStarted && localId == 0u)
        REG_SIOCNT |= SIOCNT_START;
#elif defined(PAYLOAD_NATIVE_SIO_MASTER)
    REG_SIOCNT |= SIOCNT_START;
#endif
    REG_IF = IRQ_SERIAL;
}'''
    source = replace_function(source, "SioOnSerialIrq", irq_fn, "SioOnSerialIrq")

    if "SioRxWord(u8 sourceId, u16 w)" not in source or "SioDeliverFrame(sourceId" not in source:
        raise ValueError("Per-peer SIO parser validation failed.")
    source = once(
        source,
        "/* CUBHMA_UNIFIED_LINK_ID_MASTER: physical SIO master follows hardware device ID, not menu role. */",
        "/* CUBHMA_UNIFIED_LINK_ID_MASTER: physical SIO master follows hardware device ID, not menu role. */\n"
        "/* " + SIO_MARKER + ": maintain an independent RX parser for each peer. */",
        "per-peer SIO marker",
    )
    return source, True


def patch_main(source: str) -> tuple[str, bool]:
    if MARKER in source:
        return source, False
    if "CUBHMA_UNIFIED_COMPACT_LOBBY" not in source:
        raise ValueError("Apply the compact unified lobby patch first.")
    if "CUBHMA_UNIFIED_START_MENU_REQUEST" not in source:
        raise ValueError("Apply tools/patch_unified_start_menu.py first.")

    source = once(
        source,
        "u8 SioGetNativeRole(void);\n",
        "u8 SioGetNativeRole(void);\n"
        "u8 SioGetDeviceId(void);\n"
        "int SioTxIdle(void);\n",
        "SIO helper prototypes",
    )

    deliver_fn = r'''u8 SioGetDeviceId(void);

int SioDeliverFrame(u8 sourceId, u8 type, const u16 *words, u8 count)
{
    u32 head, next, i;
    u8 localId, remoteSlot;
    const u8 *src;
    volatile u8 *dst;

    if (type != SIO_T_EVENT || count != (u8)(sizeof(struct NetEvent) / 2))
        return 1;
#ifdef PAYLOAD_NATIVE_SIO_RUNTIME
    /* Ignore incoming gameplay traffic after this console has left. Device 0
     * may still clock the cable so the other linked players can continue. */
    if (SioGetNativeRole() == CUBHMA_NATIVE_ROLE_OFF)
        return 1;
#endif
    localId = SioGetDeviceId();
    if (sourceId >= 4u || sourceId == localId)
        return 1;
    remoteSlot = (sourceId < localId) ? sourceId : (u8)(sourceId - 1u);
    if (remoteSlot >= N_REMOTES)
        return 1;

    head = g_mailbox.rxHead;
    next = WRAP(head, RX_SLOTS);
    if (next == g_mailbox.rxTail)
        return 0;

    src = (const u8 *)words;
    dst = (volatile u8 *)&g_mailbox.rx[head];
    for (i = 0; i < sizeof(struct NetEvent); i++)
        dst[i] = src[i];

    /* The event wire format stays 12 bytes; its unused type high nibble stores
     * the local remote-avatar slot assigned to this source device. */
    dst[0] = (u8)((dst[0] & 0x0Fu) | (remoteSlot << 4));
    g_mailbox.rxHead = next;
    return 1;
}'''
    pattern = r"int SioDeliverFrame\(u8 type, const u16 \*words, u8 count\)\s*\{.*?^\}"
    source, n = re.subn(pattern, lambda _: deliver_fn, source, count=1, flags=re.S | re.M)
    if n != 1:
        raise ValueError("Could not uniquely replace SioDeliverFrame.")

    # Remove the misleading 2-player suffix from the labels without changing the
    # game's character encoding, and add the existing disconnect wording.
    source = once(
        source,
        "static const u8 sNativeLobbyTextHost[] =\n"
        "    {0xC2, 0xE3, 0xE7, 0xE8, 0x00, 0x5C, 0xA3, 0xCA, 0x5D, 0xFF}; /* Host (2P) */\n"
        "static const u8 sNativeLobbyTextJoin[] =\n"
        "    {0xC4, 0xE3, 0xDD, 0xE2, 0x00, 0x5C, 0xA3, 0xCA, 0x5D, 0xFF}; /* Join (2P) */",
        "static const u8 sNativeLobbyTextHost[] =\n"
        "    {0xC2, 0xE3, 0xE7, 0xE8, 0xFF}; /* Host */\n"
        "static const u8 sNativeLobbyTextJoin[] =\n"
        "    {0xC4, 0xE3, 0xDD, 0xE2, 0xFF}; /* Join */\n"
        "static const u8 sNativeLobbyTextDisconnect[] =\n"
        "    {0xBE, 0xDD, 0xE7, 0xD7, 0xE3, 0xE2, 0xE2, 0xD9, 0xD7, 0xE8, 0xFF}; /* Disconnect */",
        "lobby option text",
    )
    source = once(
        source,
        "static u8 sNativeLobbyMenuOpen;\n"
        "static u8 sNativeLobbyCursor;\n"
        "static u8 sNativeLobbyCount;\n",
        "static u8 sNativeLobbyMenuOpen;\n"
        "static u8 sNativeLobbyCursor;\n"
        "static u8 sNativeLobbyCount;\n"
        "static u8 sNativeLeavePending;\n"
        "static u16 sNativeLeaveWait;\n",
        "leave state",
    )

    open_fn = r'''static void NativeLobbyOpen(void)
{
    u8 windowId;
    u8 role = SioGetNativeRole();

    if (role == CUBHMA_NATIVE_ROLE_OFF)
    {
        sNativeLobbyActions[0].text = sNativeLobbyTextHost;
        sNativeLobbyActions[1].text = sNativeLobbyTextJoin;
        sNativeLobbyCount = 2u;
    }
    else
    {
        sNativeLobbyActions[0].text = sNativeLobbyTextDisconnect;
        sNativeLobbyCount = 1u;
    }

    sNativeLobbyCursor = 0;
    ((void (*)(void))LoadMessageBoxAndBorderGfx)();
    windowId = ((u8 (*)(u8))AddStartMenuWindow)(sNativeLobbyCount);
    if (windowId == 0xFFu)
        return;

    sNativeLobbyMenuOpen = 1;
    LockPlayerFieldControls();
    FreezeObjectEvents();
    PlayerFreeze();
    StopPlayerAvatar();
    gMain_newKeys = 0;
    gMain_heldKeys = 0;
    NativeLobbyDraw(sNativeLobbyCursor);
}'''
    source = replace_function(source, "NativeLobbyOpen", open_fn, "NativeLobbyOpen")

    tick_fn = r'''static void EmitEvent(u8 type, u8 dir, u8 speed, s16 x, s16 y);

static void NativeLobbyBeginLeave(void)
{
    if (sNativeLeavePending)
        return;

    /* Drop stale movement, queue one leave event, and keep the transport active
     * until the final word has left the serial TX buffer. */
    g_mailbox.txTail = g_mailbox.txHead;
    EmitEvent(EVENT_LEAVE, 0, 0, 0, 0);
    EmitEvent(EVENT_LEAVE, 0, 0, 0, 0);
    EmitEvent(EVENT_LEAVE, 0, 0, 0, 0);
    sNativeLeavePending = 1;
    sNativeLeaveWait = 0;
}

static int NativeLobbyMenuTick(void)
{
    s8 choice;

    if (sNativeLeavePending)
    {
        if ((g_mailbox.txHead == g_mailbox.txTail && SioTxIdle())
            || sNativeLeaveWait >= 120u)
        {
            NativeLobbyResetSession(CUBHMA_NATIVE_ROLE_OFF);
            sNativeLeavePending = 0;
            sNativeLeaveWait = 0;
        }
        else
        {
            sNativeLeaveWait++;
        }
        return 0;
    }

    if (sNativeLobbyMenuOpen)
    {
        choice = ((s8 (*)(void))Menu_ProcessInputNoWrap)();
        gMain_newKeys = 0;
        gMain_heldKeys = 0;

        if (choice == -1)
        {
            NativeLobbyClose();
            return 1;
        }

        if (choice >= 0 && choice < sNativeLobbyCount)
        {
            if (SioGetNativeRole() == CUBHMA_NATIVE_ROLE_OFF)
            {
                NativeLobbyResetSession(choice == 0
                    ? CUBHMA_NATIVE_ROLE_HOST
                    : CUBHMA_NATIVE_ROLE_JOIN);
                NativeLobbyClose();
            }
            else
            {
                NativeLobbyBeginLeave();
                NativeLobbyClose();
            }
        }
        return 1;
    }

    if (g_lobbyRequest == CUBHMA_LOBBY_REQUEST_MAGIC
        && g_state.inOverworld
        && !ArePlayerFieldControlsLocked())
    {
        g_lobbyRequest = 0;
        NativeLobbyOpen();
        return 1;
    }

    return 0;
}'''
    # This replacement includes the forward declaration so it works regardless
    # of the lobby helper's position relative to EmitEvent's definition.
    pattern = r"static int NativeLobbyMenuTick\(void\)\s*\{.*?^\}"
    source, n = re.subn(pattern, lambda _: tick_fn, source, count=1, flags=re.S | re.M)
    if n != 1:
        raise ValueError("Could not uniquely replace NativeLobbyMenuTick.")

    # Single-player must not fill the outgoing ring with untransmittable events.
    emit_anchor = "static int EmitRaw(struct NetEvent *ev)\n{\n"
    source = once(
        source,
        emit_anchor,
        emit_anchor
        + "#ifdef PAYLOAD_NATIVE_SIO_RUNTIME\n"
        + "    if (SioGetNativeRole() == CUBHMA_NATIVE_ROLE_OFF)\n"
        + "        return 0;\n"
        + "#endif\n",
        "single-player TX gate",
    )

    if "SioDeliverFrame(u8 sourceId" not in source:
        raise ValueError("Source-aware frame delivery validation failed.")
    if "static void NativeLobbyBeginLeave(void)" not in source:
        raise ValueError("Leave flow validation failed.")
    # Marker remains inside a comment/compile-time-only path to make reruns safe.
    source = once(
        source,
        "/* CUBHMA_UNIFIED_COMPACT_LOBBY: Host/Join once per launch; restart to disconnect. */",
        "/* CUBHMA_UNIFIED_COMPACT_LOBBY: Host/Join once per launch; restart to disconnect. */\n"
        "/* " + MARKER + ": receive independent streams from all three remote slots. */",
        "capacity patch marker",
    )
    return source, True


def backup_write(path: Path, content: str) -> None:
    backup = Path(str(path) + ".pre-unified-3p4p-leave.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(content, encoding="utf-8", newline="\n")


def main() -> int:
    sio_path = SUBMODULE / "payload" / "sio.c"
    main_path = SUBMODULE / "payload" / "main.c"
    for path in (sio_path, main_path):
        if not path.is_file():
            print(f"error: required source file not found: {path}", file=sys.stderr)
            return 1

    try:
        sio_new, sio_changed = patch_sio(sio_path.read_text(encoding="utf-8"))
        main_new, main_changed = patch_main(main_path.read_text(encoding="utf-8"))

        # Validate both transformations before writing either one.
        for path, content, changed in (
            (sio_path, sio_new, sio_changed),
            (main_path, main_new, main_changed),
        ):
            if changed:
                backup_write(path, content)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Applied native multiplayer capacity/leave patch:")
    print(f"  payload/sio.c:  {'updated' if sio_changed else 'already updated'}")
    print(f"  payload/main.c: {'updated' if main_changed else 'already updated'}")
    print("")
    print("This enables up to four active linked windows (one local + three remote).")
    print("Start > Multiplayer now shows Host/Join before connecting and Disconnect while connected.")
    print("Disconnect sends EVENT_LEAVE, waits for its TX frame, clears local remotes, and leaves ID 0 clocking for peers.")
    print("")
    print("Next:")
    print("  1. Rebuild pokeemerald in WSL: wsl -e bash -lc \"cd /mnt/c/src/pokeemerald && make -j2\"")
    print("  2. Package in PowerShell: .\\tools\\prepare_unified_native_link_rom.ps1")
    print("  3. Test two players first, then three, then four. All joined ROMs must use the same build.")
    print("")
    print("Backups use .pre-unified-3p4p-leave.bak.")
    print("This source patch still needs compilation and in-emulator testing; build guards may report the payload is over its EWRAM budget.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
