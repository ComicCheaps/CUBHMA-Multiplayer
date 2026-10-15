#!/usr/bin/env python3
"""Patch native SIO for one identical runtime-selectable two-player ROM.

This first milestone keeps the tested master/slave path available. The unified
ROM defaults to single-player with SIO off and opens a small Host/Join menu with
SELECT. Four-player transport and lobby-size selection are later steps.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

RUNTIME_MARKER = "CUBHMA_UNIFIED_RUNTIME_ROLE"
MENU_MARKER = "CUBHMA_UNIFIED_LOBBY_MENU"

ROLE_DEFS = r'''/* CUBHMA_UNIFIED_RUNTIME_ROLE */
#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)
#define CUBHMA_NATIVE_ROLE_OFF  0u
#define CUBHMA_NATIVE_ROLE_HOST 1u
#define CUBHMA_NATIVE_ROLE_JOIN 2u
static volatile u8 sNativeRole = CUBHMA_NATIVE_ROLE_OFF;

void SioSetNativeRole(u8 role)
{
    if (role <= CUBHMA_NATIVE_ROLE_JOIN)
        sNativeRole = role;
}

u8 SioGetNativeRole(void)
{
    return sNativeRole;
}
#endif

'''

NEW_ARM = r'''static __attribute__((noinline)) void SioArm(void)
{
    REG_RCNT   = RCNT_SIO_MODE;
    REG_SIOCNT = SIOCNT_MULTI | SIOCNT_BAUD_115200 | SIOCNT_IRQ;
    REG_IE    |= IRQ_SERIAL;
    sSio.rxPhase = RX_WAIT_SYNC;
    REG_SIOMLT_SEND = SioPeekWord();
#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)
    /* Runtime host supplies the clock; joining ROMs wait for the host. */
    if (sNativeRole == CUBHMA_NATIVE_ROLE_HOST)
        REG_SIOCNT |= SIOCNT_START;
#elif defined(PAYLOAD_NATIVE_SIO_MASTER)
    REG_SIOCNT |= SIOCNT_START;
#endif
}'''

OLD_RX_BLOCK = r'''/* CUBHMA_NATIVE_LINK_MODE_PATCH
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

    REG_IF = IRQ_SERIAL;'''

NEW_RX_BLOCK = r'''#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)
    if (sNativeRole == CUBHMA_NATIVE_ROLE_HOST)
        SioRxWord(REG_SIOMULTI1);
    else
        SioRxWord(REG_SIOMULTI0);
#else
#if defined(PAYLOAD_NATIVE_SIO_MASTER)
    SioRxWord(REG_SIOMULTI1);
#else
    SioRxWord(REG_SIOMULTI0);
#endif
#endif

    /* The host starts the next transfer; a joining ROM waits for its clock. */
    REG_SIOMLT_SEND = SioNextWord();
#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)
    if (sNativeRole == CUBHMA_NATIVE_ROLE_HOST)
        REG_SIOCNT |= SIOCNT_START;
#elif defined(PAYLOAD_NATIVE_SIO_MASTER)
    REG_SIOCNT |= SIOCNT_START;
#endif

    REG_IF = IRQ_SERIAL;'''

LOBBY_CODE = r'''#ifdef PAYLOAD_NATIVE_SIO_RUNTIME
/* CUBHMA_UNIFIED_LOBBY_MENU
 * SELECT opens this test lobby while in the overworld. This allows one exact
 * ROM image to run either as the host or as a joiner without an auto-link.
 */
#ifndef SELECT_BUTTON
#define SELECT_BUTTON 0x0004u
#endif

static const u8 sNativeLobbyTextHost[] =
    {0xC2, 0xE3, 0xE7, 0xE8, 0x00, 0x5C, 0xA3, 0xCA, 0x5D, 0xFF}; /* Host (2P) */
static const u8 sNativeLobbyTextJoin[] =
    {0xC4, 0xE3, 0xDD, 0xE2, 0x00, 0x5C, 0xA3, 0xCA, 0x5D, 0xFF}; /* Join (2P) */
static const u8 sNativeLobbyTextDisconnect[] =
    {0xBE, 0xDD, 0xE7, 0xD7, 0xE3, 0xE2, 0xE2, 0xD9, 0xD7, 0xE8, 0xFF}; /* Disconnect */
static const u8 sNativeLobbyTextClose[] =
    {0xBD, 0xE0, 0xE3, 0xE7, 0xD9, 0xFF}; /* Close */

static struct PayloadMenuAction sNativeLobbyActions[3] =
{
    {sNativeLobbyTextHost,       {.void_u8 = 0}},
    {sNativeLobbyTextJoin,       {.void_u8 = 0}},
    {sNativeLobbyTextClose,      {.void_u8 = 0}},
};

static u8 sNativeLobbyMenuOpen;
static u8 sNativeLobbyCursor;
static u8 sNativeLobbyCount;

static void NativeLobbyDraw(u8 cursorPos)
{
    u8 windowId = ((u8 (*)(void))GetStartMenuWindowId)();

    if (windowId == 0xFFu)
        return;

    ((void (*)(u8, u8))DrawStdWindowFrame)(windowId, 0u);
    ((void (*)(u8, u8, u8, u8, u8, u8, const struct PayloadMenuAction *))PrintMenuActionTextsAtPos)(
        windowId, 1u, 8u, 9u, 16u, sNativeLobbyCount, sNativeLobbyActions);
    ((u8 (*)(u8, u8, u8, u8, u8, u8, u8))InitMenuNormal)(
        windowId, 1u, 0u, 9u, 16u, sNativeLobbyCount, cursorPos);
    ((void (*)(u8, u8))CopyWindowToVram)(windowId, 1u);
}

static void NativeLobbyClose(void)
{
    u8 windowId = ((u8 (*)(void))GetStartMenuWindowId)();

    if (sNativeLobbyMenuOpen && windowId != 0xFFu)
        ((void (*)(u8, u8))ClearStdWindowAndFrame)(windowId, 1u);
    if (sNativeLobbyMenuOpen)
        ((void (*)(void))RemoveStartMenuWindow)();

    sNativeLobbyMenuOpen = 0;
    UnfreezeObjectEvents();
    UnlockPlayerFieldControls();
    gMain_newKeys = 0;
    gMain_heldKeys = 0;
}

static void NativeLobbyOpen(void)
{
    u8 windowId;
    u8 role = SioGetNativeRole();

    if (role == CUBHMA_NATIVE_ROLE_OFF)
    {
        sNativeLobbyActions[0].text = sNativeLobbyTextHost;
        sNativeLobbyActions[1].text = sNativeLobbyTextJoin;
        sNativeLobbyActions[2].text = sNativeLobbyTextClose;
        sNativeLobbyCount = 3u;
    }
    else
    {
        sNativeLobbyActions[0].text = sNativeLobbyTextDisconnect;
        sNativeLobbyActions[1].text = sNativeLobbyTextClose;
        sNativeLobbyCount = 2u;
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
}

static void NativeLobbyResetSession(u8 role)
{
    u32 i;

    /* A new session starts from fresh queues and fresh peer state, not from
     * stale steps collected during single-player or from a previous lobby. */
    g_mailbox.txHead = 0;
    g_mailbox.txTail = 0;
    g_mailbox.rxHead = 0;
    g_mailbox.rxTail = 0;
    g_mailbox.rxApplied = 0;

    if (sDoorState != DOOR_ST_NONE)
        DoorAbort();

    for (i = 0; i < N_REMOTES; i++)
    {
        struct Remote *r = &g_remotes[i];
        if (r->state == STATE_SPAWNED || r->objectId < OBJECT_EVENTS_COUNT)
            ForgetRemote(r);
        r->state = STATE_IDLE;
        r->objectId = OBJECT_EVENTS_COUNT;
        r->known = 0;
        r->mapKey = 0;
        r->targetX = 0;
        r->targetY = 0;
        r->gender = 0;
        r->avatarState = 0;
        r->status = ST_OVERWORLD;
        r->statusAge = 0;
        r->qHead = 0;
        r->qTail = 0;
        r->lastEnqSeq = 0;
        r->forceResync = 1;
        r->cardRxBitmap = 0;
        r->settled = 0;
        r->driftRun = 0;
        r->spawnCooldown = 0;
    }

    sHavePlayerPos = 0;
    sFramesSinceSync = 0;
    sSeq = 0;
    sEntrySyncsLeft = 0;
    sEntrySyncTimer = 0;
    sCardTxIdx = 0;
    sCardTxTimer = 0;
    sCardReady = 0;

#ifdef PAYLOAD_NATIVE_SIO
    sSioSnapshotTxPending = 0;
    sSioSnapshotHaveLastSample = 0;
    sSioSnapshotHaveActive = 0;
    sSioSnapshotRxVersion = 0;
    sSioSnapshotAppliedVersion = 0;
    sSioSnapshotHeartbeatFrames = 0;
#endif

    SioSetNativeRole(role);
}

static int NativeLobbyMenuTick(void)
{
    s8 choice;

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
                if (choice == 0)
                {
                    NativeLobbyResetSession(CUBHMA_NATIVE_ROLE_HOST);
                    NativeLobbyClose();
                }
                else if (choice == 1)
                {
                    NativeLobbyResetSession(CUBHMA_NATIVE_ROLE_JOIN);
                    NativeLobbyClose();
                }
                else
                    NativeLobbyClose();
            }
            else
            {
                if (choice == 0)
                    NativeLobbyResetSession(CUBHMA_NATIVE_ROLE_OFF);
                NativeLobbyClose();
            }
        }
        return 1;
    }

    if (g_state.inOverworld
        && !ArePlayerFieldControlsLocked()
        && (gMain_newKeys & SELECT_BUTTON))
    {
        gMain_newKeys = (u16)(gMain_newKeys & ~SELECT_BUTTON);
        gMain_heldKeys = (u16)(gMain_heldKeys & ~SELECT_BUTTON);
        NativeLobbyOpen();
        return 1;
    }

    return 0;
}
#endif /* PAYLOAD_NATIVE_SIO_RUNTIME */

'''

def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"Expected exactly one {label} anchor; found {count}.")
    return source.replace(old, new, 1)

def backup_and_write(path: Path, text: str) -> None:
    backup = Path(str(path) + ".pre-unified-runtime-role.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(text, encoding="utf-8", newline="\n")

def transform_sio(source: str) -> tuple[str, bool]:
    if RUNTIME_MARKER in source:
        runtime_api_present = all(s in source for s in ("SioGetNativeRole", "PAYLOAD_NATIVE_SIO_RUNTIME"))
        legacy_role_checks_present = "sNativeRole == CUBHMA_NATIVE_ROLE_HOST" in source
        link_id_patch_present = "CUBHMA_UNIFIED_LINK_ID_MASTER" in source
        if runtime_api_present and (legacy_role_checks_present or link_id_patch_present):
            return source, False
        raise ValueError("SIO has a partial unified-runtime-role patch; inspect it manually.")

    role_anchor = "static struct SioState sSio;\n"
    source = replace_once(source, role_anchor, role_anchor + "\n" + ROLE_DEFS,
                          "SIO state/role API")
    arm_old = r'''static __attribute__((noinline)) void SioArm(void)
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
}'''
    source = replace_once(source, arm_old, NEW_ARM, "runtime SioArm")

    source = replace_once(source, OLD_RX_BLOCK, NEW_RX_BLOCK, "runtime receive/clock role")

    # Ensure there is a unique marker only after all source replacements validate.
    if "SioSetNativeRole(u8 role)" not in source or "sNativeRole == CUBHMA_NATIVE_ROLE_HOST" not in source:
        raise ValueError("Runtime role API validation failed.")
    return source, True

def transform_build(source: str) -> tuple[str, bool]:
    changed = False
    old_set = '[ValidateSet("adapter", "master", "slave")]'
    new_set = '[ValidateSet("adapter", "master", "slave", "unified")]'
    if old_set in source:
        source = source.replace(old_set, new_set, 1)
        changed = True
    elif new_set not in source:
        raise ValueError("Cannot find NativeSioRole ValidateSet in build.ps1.")

    old_error = 'throw "-NativeSioRole master/slave requires -WithSio."'
    new_error = 'throw "-NativeSioRole master/slave/unified requires -WithSio."'
    if old_error in source:
        source = source.replace(old_error, new_error, 1)
        changed = True

    role_old = '''} elseif ($NativeSioRole -eq "slave") {
    $sioRoleDefs += "-DPAYLOAD_NATIVE_SIO_SLAVE"
}
'''
    role_new = '''} elseif ($NativeSioRole -eq "slave") {
    $sioRoleDefs += "-DPAYLOAD_NATIVE_SIO_SLAVE"
} elseif ($NativeSioRole -eq "unified") {
    $sioRoleDefs += "-DPAYLOAD_NATIVE_SIO_RUNTIME"
}
'''
    if role_old in source:
        source = source.replace(role_old, role_new, 1)
        changed = True
    elif '$sioRoleDefs += "-DPAYLOAD_NATIVE_SIO_RUNTIME"' not in source:
        raise ValueError("Cannot find native SIO role compiler-definition block.")

    # Keep the snapshot transport enabled in main.c, as in existing native
    # master/slave builds, and add a distinct flag for runtime role switching.
    native_main_define = 'if ($WithSio -and $NativeSioRole -ne "adapter") { $mainDefs += "-DPAYLOAD_NATIVE_SIO" }'
    if native_main_define not in source:
        main_defs_anchor = '$mainDefs = @()\nif ($WithSio) { $mainDefs += "-DPAYLOAD_WITH_SIO" }\n'
        source = replace_once(source, main_defs_anchor, main_defs_anchor + native_main_define + '\n', "native snapshot main.c compile definition")
        changed = True

    main_anchor = 'if ($NativeSioRole -eq "master") {'
    main_runtime = 'if ($NativeSioRole -eq "unified") { $mainDefs += "-DPAYLOAD_NATIVE_SIO_RUNTIME" }\n\n'
    if main_runtime not in source:
        pos = source.find(main_anchor)
        if pos < 0:
            raise ValueError("Cannot locate native SIO role block for main.c definition.")
        source = source[:pos] + main_runtime + source[pos:]
        changed = True
    return source, changed

def transform_main(source: str) -> tuple[str, bool]:
    if MENU_MARKER in source:
        return source, False
    if "CUBHMA_REMOTE_INTERACTION_MENU" not in source or "CUBHMA_NATIVE_MOVEMENT_SNAPSHOTS" not in source:
        raise ValueError("Apply the remote interaction-menu and native movement snapshot patches first.")

    role_anchor = '#define SIO_T_DIAG      0x04     /* la sonda, pagina 2: i registri veri       */\n'
    role_insert = role_anchor + '''
#ifdef PAYLOAD_NATIVE_SIO_RUNTIME
#define CUBHMA_NATIVE_ROLE_OFF  0u
#define CUBHMA_NATIVE_ROLE_HOST 1u
#define CUBHMA_NATIVE_ROLE_JOIN 2u
void SioSetNativeRole(u8 role);
u8 SioGetNativeRole(void);
#endif
'''
    source = replace_once(source, role_anchor, role_insert, "main.c runtime SIO declarations")

    type_anchor = '''struct PayloadMenuAction
{
    const u8 *text;
    union
    {
        void (*void_u8)(u8);
        u8 (*u8_void)(void);
    } func;
};
'''
    source = replace_once(source, type_anchor, type_anchor + "\n" + LOBBY_CODE, "runtime lobby menu insertion")

    source = replace_once(
        source,
        "if (!linkBusy && !gMain_inBattle) {",
        '''if (!linkBusy && !gMain_inBattle
#ifdef PAYLOAD_NATIVE_SIO_RUNTIME
        && SioGetNativeRole() != CUBHMA_NATIVE_ROLE_OFF
#endif
    ) {''',
        "single-player SIO gate"
    )

    cb_anchors = (
        '''    if ((gMain_newKeys & A_BUTTON) && !sRemoteMenuOpen && !sRemoteMenuReopenState)
    {
''',
        '''    if (gMain_newKeys & A_BUTTON)
    {
''',
    )
    found_anchors = [anchor for anchor in cb_anchors if anchor in source]
    if len(found_anchors) != 1:
        raise ValueError(f"Expected one A-button dispatcher anchor, found {len(found_anchors)}.")
    cb_anchor = found_anchors[0]
    cb_insert = '''#ifdef PAYLOAD_NATIVE_SIO_RUNTIME
    if (NativeLobbyMenuTick())
        return;
#endif

''' + cb_anchor
    source = replace_once(source, cb_anchor, cb_insert, "payload_cb1 lobby menu hook")
    return source, True

def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/patch_unified_native_roles.py <path-to-third_party/gen3-poke-multiplayer>",
              file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    sio_path = root / "payload" / "sio.c"
    build_path = root / "build.ps1"
    main_path = root / "payload" / "main.c"
    for path in (sio_path, build_path, main_path):
        if not path.is_file():
            print(f"error: required source file not found: {path}", file=sys.stderr)
            return 1

    try:
        sio_new, sio_changed = transform_sio(sio_path.read_text(encoding="utf-8"))
        build_new, build_changed = transform_build(build_path.read_text(encoding="utf-8"))
        main_new, main_changed = transform_main(main_path.read_text(encoding="utf-8"))

        changes = (
            (sio_path, sio_new, sio_changed),
            (build_path, build_new, build_changed),
            (main_path, main_new, main_changed),
        )
        for path, content, changed in changes:
            if changed:
                backup_and_write(path, content)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Unified runtime host/join source patch applied:")
    print(f"  payload/sio.c:   {'updated' if sio_changed else 'already updated'}")
    print(f"  build.ps1:       {'updated' if build_changed else 'already updated'}")
    print(f"  payload/main.c:  {'updated' if main_changed else 'already updated'}")
    print("Single-player starts with SIO disabled; SELECT opens Host/Join/Disconnect.")
    print("Both participants must build the unified ROM. This milestone is two-player only.")
    print("Backups use the suffix .pre-unified-runtime-role.bak.")
    print("Next: run prepare_unified_native_link_rom.ps1.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
