#!/usr/bin/env python3
"""Fix remote interaction-menu input, party checks, and follower catch-up.

Edits only the local submodule source files. It never opens, modifies, or
distributes a ROM. Run from the CUBHMA-Multiplayer repository, then rebuild
the native-link ROMs with prepare_native_link_roms.ps1.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

MARKER = "CUBHMA_REMOTE_INTERACTION_MENU"
FIX_MARKER = "CUBHMA_REMOTE_INTERACTION_RESPONSIVENESS"

EXTRA_FUNCTIONS = '''    # CUBHMA_REMOTE_INTERACTION_RESPONSIVENESS: freeze field objects and gate actions on party size.
    "FreezeObjectEvents":
        "void (*)(void)",
    "UnfreezeObjectEvents":
        "void (*)(void)",
    "ClearStdWindowAndFrame":
        "void (*)(u8, u8)",
    "PlayerFreeze":
        "void (*)(void)",
    "StopPlayerAvatar":
        "void (*)(void)",
    "CalculatePlayerPartyCount":
        "u8 (*)(void)",
'''

NO_MON_TEXT = '''static const u8 sRemoteTextNoMons[] =
    {0xC8, 0xE3, 0x00, 0xC7, 0xE3, 0xE2, 0xE7, 0xFF};
'''

NEW_OPEN = '''static void OpenRemoteInteractionMenu(u32 slot)
{
    u8 windowId;

    RemoteMenuRestoreLabels();
    sRemoteMenuSlot = slot;
    sRemoteMenuCursor = 0;
    sRemoteMenuOpen = 0;

    ((void (*)(void))LoadMessageBoxAndBorderGfx)();
    windowId = ((u8 (*)(u8))AddStartMenuWindow)(REMOTE_MENU_COUNT);
    if (windowId == 0xFFu)
        return;

    sRemoteMenuOpen = 1;
    LockPlayerFieldControls();
    FreezeObjectEvents();
    PlayerFreeze();
    StopPlayerAvatar();

    /* Do not let the opening A press, or a held direction, reach field input. */
    gMain_newKeys = 0;
    gMain_heldKeys = 0;
    RemoteMenuDraw(sRemoteMenuCursor);
}
'''

NEW_CLOSE = '''static void CloseRemoteInteractionMenu(void)
{
    u8 windowId = ((u8 (*)(void))GetStartMenuWindowId)();

    /* Removing the menu window alone releases its allocation but can leave
     * the old frame/text visible in VRAM. Vanilla Emerald clears the window
     * before removing it; mirror that behavior here. */
    if (sRemoteMenuOpen && windowId != 0xFFu)
        ((void (*)(u8, u8))ClearStdWindowAndFrame)(windowId, 1u);
    if (sRemoteMenuOpen)
        ((void (*)(void))RemoveStartMenuWindow)();

    sRemoteMenuOpen = 0;
    RemoteMenuRestoreLabels();
    UnfreezeObjectEvents();
    UnlockPlayerFieldControls();
    gMain_newKeys = 0;
    gMain_heldKeys = 0;
}
'''

NEW_INPUT_BLOCK = '''static void RemoteMenuShowNotice(u8 choice, u32 noPokemon)
{
    if (choice >= REMOTE_MENU_COUNT)
        return;

    sRemoteMenuActions[choice].text = noPokemon ? sRemoteTextNoMons : sRemoteTextSoon;
    sRemoteMenuNoticeChoice = choice;
    sRemoteMenuNoticeNoPokemon = noPokemon;
    sRemoteMenuNoticeFrames = REMOTE_MENU_NOTICE_FRAMES;
    RemoteMenuDraw(choice);
}

static void RemoteInteractionMenuTick(void)
{
    u16 keys;

    if (!sRemoteMenuOpen)
        return;

    /* Take the keys for our menu, then suppress both edge and held input so
     * movement cannot leak through to the field controller while it is open. */
    keys = gMain_newKeys;
    gMain_newKeys = 0;
    gMain_heldKeys = 0;

    /* B must always close the menu, even while a temporary notice is shown. */
    if (keys & B_BUTTON)
    {
        CloseRemoteInteractionMenu();
        return;
    }

    if (sRemoteMenuNoticeFrames)
    {
        if (--sRemoteMenuNoticeFrames == 0)
        {
            u8 cursor = (u8)sRemoteMenuNoticeChoice;
            RemoteMenuRestoreLabels();
            RemoteMenuDraw(cursor);
        }
        return;
    }

    if (keys & DPAD_UP)
    {
        sRemoteMenuCursor = (sRemoteMenuCursor == 0) ? (REMOTE_MENU_COUNT - 1) : (sRemoteMenuCursor - 1);
        RemoteMenuDraw((u8)sRemoteMenuCursor);
        return;
    }
    if (keys & DPAD_DOWN)
    {
        sRemoteMenuCursor = (sRemoteMenuCursor + 1 >= REMOTE_MENU_COUNT) ? 0 : (sRemoteMenuCursor + 1);
        RemoteMenuDraw((u8)sRemoteMenuCursor);
        return;
    }
    if (!(keys & A_BUTTON))
        return;

    if (sRemoteMenuCursor == 0) /* Trainer Card */
    {
        if (g_remotes[sRemoteMenuSlot].cardRxBitmap == CARD_ALL_CHUNKS
            && !sCardShowWait && g_state.inOverworld)
        {
            ((void (*)(void))RemoveStartMenuWindow)();
            sRemoteMenuOpen = 0;
            sCardShowSlot = sRemoteMenuSlot;
            sRemoteMenuReopenState = 1u;
            FadeScreen(FADE_TO_BLACK, 0);
            sCardShowWait = CARD_FADE_FRAMES;
        }
        else if (!sCardShowWait && g_state.inOverworld)
        {
            RemoteMenuShowNotice(0u, 0u);
        }
    }
    else if (sRemoteMenuCursor == 1 || sRemoteMenuCursor == 2)
    {
        /* Emerald cannot trade or battle without at least one party Pokémon.
         * Actual online Trade/Battle protocols are still separate work. */
        if (CalculatePlayerPartyCount() == 0)
            RemoteMenuShowNotice((u8)sRemoteMenuCursor, 1u);
        else
            RemoteMenuShowNotice((u8)sRemoteMenuCursor, 0u);
    }
}
'''

def backup_and_write(path: Path, new_text: str) -> None:
    backup = Path(str(path) + ".pre-menu-responsiveness.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(new_text, encoding="utf-8", newline="\n")

def ensure_functions(gen: str) -> tuple[str, bool]:
    changed = False

    # Migrate the old helper's nonexistent PlayerUnfreeze symbol to Emerald's
    # actual paired object-event functions.
    old_unfreeze = '''    "PlayerUnfreeze":
        "void (*)(void)",
'''
    new_freeze_pair = '''    "FreezeObjectEvents":
        "void (*)(void)",
    "UnfreezeObjectEvents":
        "void (*)(void)",
'''
    if old_unfreeze in gen:
        gen = gen.replace(old_unfreeze, new_freeze_pair, 1)
        changed = True

    signatures = (
        ("FreezeObjectEvents", '"void (*)(void)"'),
        ("UnfreezeObjectEvents", '"void (*)(void)"'),
        ("ClearStdWindowAndFrame", '"void (*)(u8, u8)"'),
        ("PlayerFreeze", '"void (*)(void)"'),
        ("StopPlayerAvatar", '"void (*)(void)"'),
        ("CalculatePlayerPartyCount", '"u8 (*)(void)"'),
    )
    missing = [(name, signature) for name, signature in signatures
               if f'"{name}":' not in gen]
    if missing:
        # Locate the function-table entry without relying on escaped newlines.
        anchor = '    "LoadMessageBoxAndBorderGfx":'
        pos = gen.find(anchor)
        if pos < 0:
            raise ValueError("Cannot find LoadMessageBoxAndBorderGfx in tools/gen_syms.py.")
        additions = "".join(f'    "{name}":\n        {signature},\n' for name, signature in missing)
        gen = gen[:pos] + additions + gen[pos:]
        changed = True

    return gen, changed

def replace_function(source: str, name: str, new_function: str) -> tuple[str, bool]:
    start_token = f"static void {name}("
    start = source.find(start_token)
    if start < 0:
        if new_function.strip() in source:
            return source, False
        raise ValueError(f"Could not find function {name} in payload/main.c.")
    next_function = source.find("\nstatic ", start + len(start_token))
    if next_function < 0:
        raise ValueError(f"Could not find the next function boundary after {name}.")
    old = source[start:next_function + 1]
    replacement = new_function.rstrip() + "\n\n"
    if old == replacement:
        return source, False
    return source[:start] + replacement + source[next_function + 1:], True

def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/fix_remote_interaction_responsiveness.py <path-to-third_party/gen3-poke-multiplayer>",
              file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    gen_path = root / "tools" / "gen_syms.py"
    main_path = root / "payload" / "main.c"
    for path in (gen_path, main_path):
        if not path.is_file():
            print(f"error: required source file not found: {path}", file=sys.stderr)
            return 1

    try:
        gen = gen_path.read_text(encoding="utf-8")
        source = main_path.read_text(encoding="utf-8")
        if MARKER not in source:
            raise ValueError("The native remote interaction-menu patch is missing. Apply tools/patch_remote_interaction_menu.py first.")

        new_gen, gen_changed = ensure_functions(gen)
        new_source = source
        source_changed = False

        # Migrate earlier helper versions and repair function macro names.
        for name in (
            "LoadMessageBoxAndBorderGfx", "AddStartMenuWindow", "DrawStdWindowFrame",
            "PrintMenuActionTextsAtPos", "InitMenuNormal", "CopyWindowToVram",
            "Menu_ProcessInputNoWrap", "GetStartMenuWindowId", "RemoveStartMenuWindow",
        ):
            new_name = "ADDR_" + name
            if new_name in new_source:
                new_source = new_source.replace(new_name, name)
                source_changed = True

        # The player object has no PlayerUnfreeze symbol in Emerald. Unfreezing
        # object events is the matching API; stop/freezing follows the same
        # sequence used by the vanilla START menu.
        if "PlayerUnfreeze();" in new_source:
            new_source = new_source.replace("PlayerUnfreeze();", "UnfreezeObjectEvents();")
            source_changed = True
        # Always repair the close handler on existing patched source too.
        new_source, close_changed = replace_function(new_source, "CloseRemoteInteractionMenu", NEW_CLOSE)
        source_changed = source_changed or close_changed

        old_open_freeze = "    LockPlayerFieldControls();\n    PlayerFreeze();\n    StopPlayerAvatar();"
        new_open_freeze = "    LockPlayerFieldControls();\n    FreezeObjectEvents();\n    PlayerFreeze();\n    StopPlayerAvatar();"
        if old_open_freeze in new_source:
            new_source = new_source.replace(old_open_freeze, new_open_freeze, 1)
            source_changed = True

        # The payload's minimal game_types.h defines A_BUTTON but not B_BUTTON.
        # GBA KEY_B is bit 1 (0x0002). Define the missing symbol locally.
        if "#define B_BUTTON" not in new_source:
            include_anchor = '#include "game_types.h"\n'
            if include_anchor not in new_source:
                raise ValueError('Cannot find #include "game_types.h" in payload/main.c.')
            new_source = new_source.replace(
                include_anchor,
                include_anchor + '\n#ifndef B_BUTTON\n#define B_BUTTON 0x0002u\n#endif\n',
                1,
            )
            source_changed = True

        if FIX_MARKER not in new_source:
            # Add the missing state fields once.
            state_anchor = "static u32 sRemoteMenuNoticeChoice;"
            if state_anchor not in new_source:
                raise ValueError("Could not find the remote-menu state block.")
            new_source = new_source.replace(
                state_anchor,
                state_anchor + "\nstatic u32 sRemoteMenuCursor;\nstatic u32 sRemoteMenuNoticeNoPokemon;\n",
                1,
            )

            # Add the English 'No Mons' label using Emerald's encoded characters.
            soon_anchor = '''static const u8 sRemoteTextSoon[] =
    {0xCD, 0xE3, 0xE3, 0xE2, 0xFF};
'''
            if soon_anchor not in new_source:
                raise ValueError("Could not find the temporary menu-notice label.")
            new_source = new_source.replace(soon_anchor, soon_anchor + NO_MON_TEXT, 1)

            # Restore resets the temporary notice flag as well.
            restore = '''static void RemoteMenuRestoreLabels(void)
{
    sRemoteMenuActions[0].text = sRemoteTextTrainerCard;
    sRemoteMenuActions[1].text = sRemoteTextTrade;
    sRemoteMenuActions[2].text = sRemoteTextBattle;
    sRemoteMenuNoticeFrames = 0;
    sRemoteMenuNoticeChoice = 0;
}'''
            restore_new = '''static void RemoteMenuRestoreLabels(void)
{
    sRemoteMenuActions[0].text = sRemoteTextTrainerCard;
    sRemoteMenuActions[1].text = sRemoteTextTrade;
    sRemoteMenuActions[2].text = sRemoteTextBattle;
    sRemoteMenuNoticeFrames = 0;
    sRemoteMenuNoticeChoice = 0;
    sRemoteMenuNoticeNoPokemon = 0;
}'''
            if restore not in new_source:
                if restore_new not in new_source:
                    raise ValueError("Could not find RemoteMenuRestoreLabels to patch.")
            else:
                new_source = new_source.replace(restore, restore_new, 1)

            new_source, _ = replace_function(new_source, "OpenRemoteInteractionMenu", NEW_OPEN)
            new_source, _ = replace_function(new_source, "CloseRemoteInteractionMenu", NEW_CLOSE)

            # Replace the notice handler and input loop as one block.
            start = new_source.find("static void RemoteMenuShowSoon(u8 choice)")
            end = new_source.find("static void RemoteMenuReturnTick(void)", start)
            if start < 0 or end < 0:
                raise ValueError("Could not find the current menu notice/input handlers.")
            new_source = new_source[:start] + NEW_INPUT_BLOCK + "\n" + new_source[end:]

            # The follower should enter catch-up movement as soon as a small backlog forms.
            old_threshold = "#define HURRY_THRESHOLD     4u"
            new_threshold = "#define HURRY_THRESHOLD     2u"
            if old_threshold in new_source:
                new_source = new_source.replace(old_threshold, new_threshold, 1)
            elif new_threshold not in new_source:
                raise ValueError("Could not find HURRY_THRESHOLD in payload/main.c.")

            new_source = new_source.replace(
                "/* CUBHMA_REMOTE_INTERACTION_MENU: state for the remote-player action list. */",
                "/* CUBHMA_REMOTE_INTERACTION_MENU: state for the remote-player action list. */\n/* CUBHMA_REMOTE_INTERACTION_RESPONSIVENESS */",
                1,
            )
            source_changed = True
        else:
            # Idempotent rerun: repair function references and verify expected changes.
            required = (
                "gMain_heldKeys = 0;",
                "CalculatePlayerPartyCount() == 0",
                "#define HURRY_THRESHOLD     2u",
                "keys & B_BUTTON",
                "UnfreezeObjectEvents();",
                "FreezeObjectEvents();",
            )
            if not all(item in new_source for item in required):
                raise ValueError("Responsiveness patch marker is present but expected fixes are incomplete; inspect payload/main.c.")

        # Write only after both files have been fully validated in memory.
        if gen_changed:
            backup_and_write(gen_path, new_gen)
        if source_changed:
            backup_and_write(main_path, new_source)

    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Remote interaction responsiveness patch prepared:")
    print(f"  tools/gen_syms.py: {'updated' if gen_changed else 'already updated'}")
    print(f"  payload/main.c:    {'updated' if source_changed else 'already updated'}")
    print("Backups use the suffix .pre-menu-responsiveness.bak.")
    print("Changes: lock player input, B always closes the menu, Trade/Battle are gated by party size, and follower catch-up starts earlier.")
    print("Now rebuild the native-link test ROMs with prepare_native_link_roms.ps1.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
