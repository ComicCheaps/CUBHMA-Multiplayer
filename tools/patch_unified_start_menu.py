#!/usr/bin/env python3
"""Add Start > Multiplayer and make unified SIO independent of emulator window order.

Run from the CUBHMA-Multiplayer checkout:
  python tools/patch_unified_start_menu.py C:\src\pokeemerald

The game source must then be rebuilt before packaging the unified ROM.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

GAME_MARKER = "CUBHMA_UNIFIED_START_MENU_MULTIPLAYER"
REQUEST_MARKER = "CUBHMA_UNIFIED_START_MENU_REQUEST"
LINK_ID_MARKER = "CUBHMA_UNIFIED_LINK_ID_MASTER"
REQUEST_MAGIC = "0x594C504Du"  # ASCII MPLY in little-endian memory
REQUEST_ADDRESS = "0x0203CF8Cu"  # payload header word at base + 0x0C


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"Could not uniquely patch {label} (matches={count}).")
    return source.replace(old, new, 1)


def patch_game_start_menu(source: str) -> tuple[str, bool]:
    if GAME_MARKER in source:
        return source, False

    source = replace_once(
        source,
        "    MENU_ACTION_RETIRE_FRONTIER,\n    MENU_ACTION_PYRAMID_BAG\n};",
        "    MENU_ACTION_RETIRE_FRONTIER,\n    MENU_ACTION_PYRAMID_BAG,\n    MENU_ACTION_MULTIPLAYER\n};",
        "start-menu action enum",
    )
    source = replace_once(
        source,
        "// Menu action callbacks\n",
        "/* " + GAME_MARKER + ": adds a Start-menu entry routed to the payload lobby. */\n"
        "#define CUBHMA_MULTIPLAYER_REQUEST_ADDR " + REQUEST_ADDRESS + "\n"
        "#define CUBHMA_MULTIPLAYER_REQUEST_MAGIC " + REQUEST_MAGIC + "\n"
        "static const u8 sText_MenuMultiplayer[] = _(\"Multiplayer\");\n\n"
        "// Menu action callbacks\n",
        "multiplayer label and request marker",
    )
    source = replace_once(
        source,
        "static bool8 StartMenuBattlePyramidBagCallback(void);\n",
        "static bool8 StartMenuBattlePyramidBagCallback(void);\n"
        "static bool8 StartMenuMultiplayerCallback(void);\n",
        "multiplayer callback declaration",
    )
    source = replace_once(
        source,
        "    [MENU_ACTION_PYRAMID_BAG]     = {gText_MenuBag,     {.u8_void = StartMenuBattlePyramidBagCallback}}\n};",
        "    [MENU_ACTION_PYRAMID_BAG]     = {gText_MenuBag,     {.u8_void = StartMenuBattlePyramidBagCallback}},\n"
        "    [MENU_ACTION_MULTIPLAYER]    = {sText_MenuMultiplayer, {.u8_void = StartMenuMultiplayerCallback}}\n};",
        "start-menu action table",
    )
    source = replace_once(
        source,
        "    AddStartMenuAction(MENU_ACTION_PLAYER);\n"
        "    AddStartMenuAction(MENU_ACTION_SAVE);\n"
        "    AddStartMenuAction(MENU_ACTION_OPTION);\n"
        "    AddStartMenuAction(MENU_ACTION_EXIT);\n"
        "}\n\nstatic void BuildSafariZoneStartMenu",
        "    AddStartMenuAction(MENU_ACTION_PLAYER);\n"
        "    AddStartMenuAction(MENU_ACTION_SAVE);\n"
        "    AddStartMenuAction(MENU_ACTION_MULTIPLAYER);\n"
        "    AddStartMenuAction(MENU_ACTION_OPTION);\n"
        "    AddStartMenuAction(MENU_ACTION_EXIT);\n"
        "}\n\nstatic void BuildSafariZoneStartMenu",
        "normal start-menu action list",
    )
    source = replace_once(
        source,
        "            && gMenuCallback != StartMenuBattlePyramidRetireCallback)",
        "            && gMenuCallback != StartMenuBattlePyramidRetireCallback\n"
        "            && gMenuCallback != StartMenuMultiplayerCallback)",
        "multiplayer fade exclusion",
    )

    exit_block = (
        "static bool8 StartMenuExitCallback(void)\n"
        "{\n"
        "    RemoveExtraStartMenuWindows();\n"
        "    HideStartMenu(); // Hide start menu\n\n"
        "    return TRUE;\n"
        "}\n\n"
        "static bool8 StartMenuSafariZoneRetireCallback(void)"
    )
    replacement = (
        "static bool8 StartMenuExitCallback(void)\n"
        "{\n"
        "    RemoveExtraStartMenuWindows();\n"
        "    HideStartMenu(); // Hide start menu\n\n"
        "    return TRUE;\n"
        "}\n\n"
        "static bool8 StartMenuMultiplayerCallback(void)\n"
        "{\n"
        "    RemoveExtraStartMenuWindows();\n"
        "    HideStartMenuWindow();\n"
        "    *(volatile u32 *)CUBHMA_MULTIPLAYER_REQUEST_ADDR = CUBHMA_MULTIPLAYER_REQUEST_MAGIC;\n"
        "    return TRUE;\n"
        "}\n\n"
        "static bool8 StartMenuSafariZoneRetireCallback(void)"
    )
    source = replace_once(source, exit_block, replacement, "multiplayer callback body")
    return source, True


def patch_hook(source: str) -> tuple[str, bool]:
    if "g_lobbyRequest:" in source:
        if REQUEST_MARKER in source:
            return source, False
        raise ValueError("hook.S contains g_lobbyRequest without the expected marker.")
    anchor = "    .word   0x4B4F4F48          @ \"HOOK\" in little endian\n"
    updated = replace_once(
        source,
        anchor,
        anchor
        + "\n    .global g_lobbyRequest\n"
        + "g_lobbyRequest:\n"
        + "    .word   0                   @ " + REQUEST_MARKER + "\n",
        "payload-header lobby request word",
    )
    return updated, True


def patch_payload_main(source: str) -> tuple[str, bool]:
    if "CUBHMA_UNIFIED_COMPACT_LOBBY" not in source:
        raise ValueError(
            "payload/main.c is missing the compact unified lobby patch. "
            "Apply the existing unified-role and compact-lobby helpers first."
        )

    changed = False
    if REQUEST_MARKER not in source:
        anchor = (
            "#ifdef PAYLOAD_NATIVE_SIO_RUNTIME\n"
            "/* CUBHMA_UNIFIED_COMPACT_LOBBY: Host/Join once per launch; restart to disconnect. */"
        )
        insert = (
            "#ifdef PAYLOAD_NATIVE_SIO_RUNTIME\n"
            "/* CUBHMA_UNIFIED_COMPACT_LOBBY: Host/Join once per launch; restart to disconnect. */\n"
            "/* " + REQUEST_MARKER + " */\n"
            "extern volatile u32 g_lobbyRequest;\n"
            "#define CUBHMA_LOBBY_REQUEST_MAGIC " + REQUEST_MAGIC + "\n"
        )
        source = replace_once(source, anchor, insert, "payload lobby request declaration")
        changed = True

    new_tick = r'''static int NativeLobbyMenuTick(void)
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
        if (choice >= 0 && choice < 2)
        {
            NativeLobbyResetSession(choice == 0
                ? CUBHMA_NATIVE_ROLE_HOST
                : CUBHMA_NATIVE_ROLE_JOIN);
            NativeLobbyClose();
        }
        return 1;
    }

    /* The real Start menu writes this request after it closes its own window.
     * The payload then opens Host/Join using its existing safe menu routines. */
    if (g_lobbyRequest == CUBHMA_LOBBY_REQUEST_MAGIC
        && g_state.inOverworld
        && !ArePlayerFieldControlsLocked())
    {
        g_lobbyRequest = 0;
        if (SioGetNativeRole() == CUBHMA_NATIVE_ROLE_OFF)
        {
            NativeLobbyOpen();
            return 1;
        }
    }

    return 0;
}'''
    pattern = r"static int NativeLobbyMenuTick\(void\)\s*\{.*?\n\}"
    updated, count = re.subn(pattern, lambda _: new_tick, source, count=1, flags=re.S)
    if count != 1:
        raise ValueError("Could not uniquely replace NativeLobbyMenuTick.")
    if updated != source:
        changed = True
    source = updated

    if REQUEST_MARKER not in source or "g_lobbyRequest == CUBHMA_LOBBY_REQUEST_MAGIC" not in source:
        raise ValueError("Payload lobby-request validation failed.")
    return source, changed


def patch_sio(source: str) -> tuple[str, bool]:
    if LINK_ID_MARKER in source:
        return source, False
    if "CUBHMA_UNIFIED_RUNTIME_ROLE" not in source:
        raise ValueError("payload/sio.c is missing the unified runtime role patch.")

    old_clock = (
        "if (sNativeRole == CUBHMA_NATIVE_ROLE_HOST)\n"
        "        REG_SIOCNT |= SIOCNT_START;"
    )
    new_clock = (
        "if ((REG_SIOCNT & 0x0030u) == 0u)\n"
        "        REG_SIOCNT |= SIOCNT_START;"
    )
    count = source.count(old_clock)
    if count != 2:
        raise ValueError(f"Expected two runtime host-clock checks in sio.c; found {count}.")
    source = source.replace(old_clock, new_clock)

    old_receive = (
        "#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n"
        "    if (sNativeRole == CUBHMA_NATIVE_ROLE_HOST)\n"
        "        SioRxWord(REG_SIOMULTI1);\n"
        "    else\n"
        "        SioRxWord(REG_SIOMULTI0);\n"
        "#else\n"
        "#if defined(PAYLOAD_NATIVE_SIO_MASTER)"
    )
    new_receive = (
        "#if defined(PAYLOAD_NATIVE_SIO_RUNTIME)\n"
        "    /* mGBA assigns a fixed serial device ID to each linked window. ID 0\n"
        "     * reads the peer from slot 1; child IDs read the parent from slot 0. */\n"
        "    if ((REG_SIOCNT & 0x0030u) == 0u)\n"
        "        SioRxWord(REG_SIOMULTI1);\n"
        "    else\n"
        "        SioRxWord(REG_SIOMULTI0);\n"
        "#else\n"
        "#if defined(PAYLOAD_NATIVE_SIO_MASTER)"
    )
    source = replace_once(source, old_receive, new_receive, "runtime receive slot")
    source = source.replace(
        "/* Runtime host supplies the clock; joining ROMs wait for the host. */",
        "/* The linked emulator's device ID 0 supplies the clock, independent of Host/Join. */",
        1,
    )
    source = source.replace(
        "/* The host starts the next transfer; a joining ROM waits for its clock. */",
        "/* The linked emulator's device ID 0 starts each next transfer. */",
        1,
    )
    anchor = "static __attribute__((noinline)) void SioArm(void)\n{"
    source = replace_once(
        source,
        anchor,
        "/* " + LINK_ID_MARKER + ": physical SIO master follows hardware device ID, not menu role. */\n"
        + anchor,
        "serial device-ID marker",
    )
    return source, True


def backup_and_write(path: Path, text: str, suffix: str) -> None:
    backup = Path(str(path) + suffix)
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print(
            "Usage: python tools/patch_unified_start_menu.py <path-to-pokeemerald> "
            "[path-to-third_party/gen3-poke-multiplayer]",
            file=sys.stderr,
        )
        return 2

    game_root = Path(sys.argv[1]).resolve()
    submodule_root = (
        Path(sys.argv[2]).resolve()
        if len(sys.argv) == 3
        else Path(__file__).resolve().parent.parent / "third_party" / "gen3-poke-multiplayer"
    )
    game_path = game_root / "src" / "start_menu.c"
    hook_path = submodule_root / "payload" / "hook.S"
    main_path = submodule_root / "payload" / "main.c"
    sio_path = submodule_root / "payload" / "sio.c"

    for path in (game_path, hook_path, main_path, sio_path):
        if not path.is_file():
            print(f"error: required file not found: {path}", file=sys.stderr)
            return 1

    try:
        game_new, game_changed = patch_game_start_menu(game_path.read_text(encoding="utf-8"))
        hook_new, hook_changed = patch_hook(hook_path.read_text(encoding="utf-8"))
        main_new, main_changed = patch_payload_main(main_path.read_text(encoding="utf-8"))
        sio_new, sio_changed = patch_sio(sio_path.read_text(encoding="utf-8"))

        changes = (
            (game_path, game_new, game_changed, ".pre-unified-start-menu.bak"),
            (hook_path, hook_new, hook_changed, ".pre-unified-start-menu.bak"),
            (main_path, main_new, main_changed, ".pre-unified-start-menu.bak"),
            (sio_path, sio_new, sio_changed, ".pre-unified-start-menu.bak"),
        )
        # Every replacement is validated before any file is written.
        for path, text, changed, suffix in changes:
            if changed:
                backup_and_write(path, text, suffix)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Applied unified multiplayer menu and serial-role fix:")
    print(f"  src/start_menu.c: {'updated' if game_changed else 'already updated'}")
    print(f"  payload/hook.S:   {'updated' if hook_changed else 'already updated'}")
    print(f"  payload/main.c:   {'updated' if main_changed else 'already updated'}")
    print(f"  payload/sio.c:    {'updated' if sio_changed else 'already updated'}")
    print("")
    print("Next steps:")
    print("  1. Rebuild pokeemerald in WSL: cd /mnt/c/src/pokeemerald && make -j2")
    print("  2. In PowerShell, run tools/prepare_unified_native_link_rom.ps1")
    print("  3. Load the resulting Emerald-unified.gba in both mGBA multiplayer windows.")
    print("")
    print("Backups use the suffix .pre-unified-start-menu.bak.")
    print("This patch is a targeted source change and still needs an in-emulator multiplayer test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
