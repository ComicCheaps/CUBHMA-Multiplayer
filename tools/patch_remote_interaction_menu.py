#!/usr/bin/env python3
"""Add a native three-option interaction menu for remote players.

This edits the local multiplayer payload source and its symbol generator only.
It does not read, modify, or distribute any ROM. Run fix_remote_card_return.py
first, then this script, then rebuild the native-link test ROMs.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

GEN_MARKER = "# CUBHMA_REMOTE_INTERACTION_MENU"
MAIN_MARKER = "CUBHMA_REMOTE_INTERACTION_MENU"

GEN_ANCHOR = '    "TrainerCard_GenerateCardForLinkPlayer":\n'
GEN_INSERT = '''    # CUBHMA_REMOTE_INTERACTION_MENU: native Emerald menu API used by the payload.
    "LoadMessageBoxAndBorderGfx":
        "void (*)(void)",
    "AddStartMenuWindow":
        "u8 (*)(u8 numActions)",
    "DrawStdWindowFrame":
        "void (*)(u8 windowId, bool8 copyToVram)",
    "PrintMenuActionTextsAtPos":
        "void (*)(u8 windowId, u8 fontId, u8 left, u8 top, u8 lineHeight, u8 itemCount, const void *menuActions)",
    "InitMenuNormal":
        "u8 (*)(u8 windowId, u8 fontId, u8 left, u8 top, u8 cursorHeight, u8 numChoices, u8 initialCursorPos)",
    "CopyWindowToVram":
        "void (*)(u8 windowId, u8 mode)",
    "Menu_ProcessInputNoWrap":
        "s8 (*)(void)",
    "GetStartMenuWindowId":
        "u8 (*)(void)",
    "RemoveStartMenuWindow":
        "void (*)(void)",
    "TrainerCard_GenerateCardForLinkPlayer":
'''

GLOBAL_ANCHOR = "static u32 sCardShowSlot;\n"
GLOBAL_INSERT = '''static u32 sCardShowSlot;

/* CUBHMA_REMOTE_INTERACTION_MENU: state for the remote-player action list. */
static u32 sRemoteMenuOpen;
static u32 sRemoteMenuSlot;
static u32 sRemoteMenuReopenState; /* 1 = waiting for card screen, 2 = waiting to return */
static u32 sRemoteMenuNoticeFrames;
static u32 sRemoteMenuNoticeChoice;
'''

CALLBACK_ANCHOR = "static void OverworldTick(void);\n"
CALLBACK_INSERT = r'''static void OverworldTick(void);

/* CUBHMA_REMOTE_INTERACTION_MENU
 * These are Pokémon Emerald text-encoding bytes, not ASCII strings. */
struct PayloadMenuAction
{
    const u8 *text;
    union
    {
        void (*void_u8)(u8);
        u8 (*u8_void)(void);
    } func;
};

static const u8 sRemoteTextTrainerCard[] =
    {0xCE, 0xE6, 0xD5, 0xDD, 0xE2, 0xD9, 0xE6, 0x00, 0xBD, 0xD5, 0xE6, 0xD8, 0xFF};
static const u8 sRemoteTextTrade[] =
    {0xCE, 0xE6, 0xD5, 0xD8, 0xD9, 0xFF};
static const u8 sRemoteTextBattle[] =
    {0xBC, 0xD5, 0xE8, 0xE8, 0xE0, 0xD9, 0xFF};
static const u8 sRemoteTextSoon[] =
    {0xCD, 0xE3, 0xE3, 0xE2, 0xFF};

static struct PayloadMenuAction sRemoteMenuActions[3] =
{
    {sRemoteTextTrainerCard, {.void_u8 = 0}},
    {sRemoteTextTrade,       {.void_u8 = 0}},
    {sRemoteTextBattle,      {.void_u8 = 0}},
};

#define REMOTE_MENU_COUNT 3u
#define REMOTE_MENU_NOTICE_FRAMES 90u
#define REMOTE_MENU_FONT_NORMAL 1u
#define REMOTE_MENU_COPY_MAP 1u

static void RemoteMenuRestoreLabels(void)
{
    sRemoteMenuActions[0].text = sRemoteTextTrainerCard;
    sRemoteMenuActions[1].text = sRemoteTextTrade;
    sRemoteMenuActions[2].text = sRemoteTextBattle;
    sRemoteMenuNoticeFrames = 0;
    sRemoteMenuNoticeChoice = 0;
}

static void RemoteMenuDraw(u8 cursorPos)
{
    u8 windowId = ((u8 (*)(void))ADDR_GetStartMenuWindowId)();

    if (windowId == 0xFFu)
        return;

    ((void (*)(u8, u8))ADDR_DrawStdWindowFrame)(windowId, 0u);
    ((void (*)(u8, u8, u8, u8, u8, u8, const struct PayloadMenuAction *))ADDR_PrintMenuActionTextsAtPos)(
        windowId, REMOTE_MENU_FONT_NORMAL, 8u, 9u, 16u, REMOTE_MENU_COUNT, sRemoteMenuActions);
    ((u8 (*)(u8, u8, u8, u8, u8, u8, u8))ADDR_InitMenuNormal)(
        windowId, REMOTE_MENU_FONT_NORMAL, 0u, 9u, 16u, REMOTE_MENU_COUNT, cursorPos);
    ((void (*)(u8, u8))ADDR_CopyWindowToVram)(windowId, REMOTE_MENU_COPY_MAP);
}

static void OpenRemoteInteractionMenu(u32 slot)
{
    u8 windowId;

    RemoteMenuRestoreLabels();
    sRemoteMenuSlot = slot;
    sRemoteMenuOpen = 0;
    ((void (*)(void))ADDR_LoadMessageBoxAndBorderGfx)();
    windowId = ((u8 (*)(u8))ADDR_AddStartMenuWindow)(REMOTE_MENU_COUNT);
    if (windowId == 0xFFu)
    {
        UnlockPlayerFieldControls();
        return;
    }

    sRemoteMenuOpen = 1;
    LockPlayerFieldControls();
    RemoteMenuDraw(0u);
}

static void CloseRemoteInteractionMenu(void)
{
    if (sRemoteMenuOpen)
        ((void (*)(void))ADDR_RemoveStartMenuWindow)();

    sRemoteMenuOpen = 0;
    RemoteMenuRestoreLabels();
    UnlockPlayerFieldControls();
}

static void RemoteMenuShowSoon(u8 choice)
{
    if (choice >= REMOTE_MENU_COUNT)
        return;

    sRemoteMenuActions[choice].text = sRemoteTextSoon;
    sRemoteMenuNoticeChoice = choice;
    sRemoteMenuNoticeFrames = REMOTE_MENU_NOTICE_FRAMES;
    RemoteMenuDraw(choice);
}

static void RemoteInteractionMenuTick(void)
{
    s8 choice;

    if (!sRemoteMenuOpen)
        return;

    /* Keep the game from treating this menu's key presses as field input. */
    if (sRemoteMenuNoticeFrames)
    {
        gMain_newKeys = 0;
        if (--sRemoteMenuNoticeFrames == 0)
        {
            u8 cursor = (u8)sRemoteMenuNoticeChoice;
            RemoteMenuRestoreLabels();
            RemoteMenuDraw(cursor);
        }
        return;
    }

    choice = ((s8 (*)(void))ADDR_Menu_ProcessInputNoWrap)();
    gMain_newKeys = 0;

    if (choice == -1) /* B cancels */
    {
        CloseRemoteInteractionMenu();
    }
    else if (choice == 0) /* Trainer Card */
    {
        if (g_remotes[sRemoteMenuSlot].cardRxBitmap == CARD_ALL_CHUNKS
            && !sCardShowWait && g_state.inOverworld)
        {
            ((void (*)(void))ADDR_RemoveStartMenuWindow)();
            sRemoteMenuOpen = 0;
            sCardShowSlot = sRemoteMenuSlot;
            sRemoteMenuReopenState = 1u;
            FadeScreen(FADE_TO_BLACK, 0);
            sCardShowWait = CARD_FADE_FRAMES;
        }
        else if (!sCardShowWait && g_state.inOverworld)
        {
            RemoteMenuShowSoon(0u);
        }
    }
    else if (choice == 1 || choice == 2) /* Trade/Battle are honest placeholders for now */
    {
        RemoteMenuShowSoon((u8)choice);
    }
}

static void RemoteMenuReturnTick(void)
{
    if (sRemoteMenuReopenState == 1u && !g_state.inOverworld)
    {
        sRemoteMenuReopenState = 2u;
    }
    else if (sRemoteMenuReopenState == 2u && g_state.inOverworld)
    {
        sRemoteMenuReopenState = 0u;
        OpenRemoteInteractionMenu(sRemoteMenuSlot);
    }
}
'''

A_ANCHOR = '''    if (gMain_newKeys & A_BUTTON)
    {
'''
A_REPLACEMENT = '''    if ((gMain_newKeys & A_BUTTON) && !sRemoteMenuOpen && !sRemoteMenuReopenState)
    {
'''

COMMENT_OLD = '''                /* A non arriva MAI al gioco (il percorso dello script NULL
                 * resta vietato). Ma se la scheda dell'amico e' completa e il
                 * remoto e' proprio davanti, la pressione diventa LA SCHEDA:
                 * fade come fa il menu START per la propria card
                 * (start_menu.c:623), controlli bloccati perche' nel mezzo
                 * secondo di fade il giocatore non possa avviare dialoghi o
                 * warp. Lo sblocco al ritorno lo fa il menu START, che e' il
                 * cb2 di rientro del viewer. */
'''
COMMENT_NEW = '''                /* CUBHMA_REMOTE_INTERACTION_MENU: keep the press away from the
                 * game's script dispatcher and open our native three-choice menu. */
'''

CARD_IF_OLD = '''                if (cls == 1 && g_remotes[slot].cardRxBitmap == CARD_ALL_CHUNKS
                    && !sCardShowWait && g_state.inOverworld)
                {
                    LockPlayerFieldControls();
                    FadeScreen(FADE_TO_BLACK, 0);
                    sCardShowWait = CARD_FADE_FRAMES;
                    sCardShowSlot = slot;
                }
                else if (cls == 1)
                {
                    BUMPF(aBlocked);
                }'''
CARD_IF_NEW = '''                if (cls == 1 && !sCardShowWait && g_state.inOverworld)
                {
                    OpenRemoteInteractionMenu(slot);
                    gMain_newKeys = 0;
                }
                else if (cls == 1)
                {
                    BUMPF(aBlocked);
                }'''

MENU_TICK_ANCHOR = '''    /* Il fade e' partito: allo scadere dell'attesa si cede lo schermo al
     * viewer del gioco. La lingua va scritta in gLinkPlayers[1] PRIMA:
     * ShowTrainerCardInLink la legge da li' per il font, e a 0 la scheda
     * uscirebbe con la resa giapponese. */
    if (sCardShowWait)'''
MENU_TICK_INSERT = '''    /* CUBHMA_REMOTE_INTERACTION_MENU: consume list-menu input before the game's callback. */
    RemoteInteractionMenuTick();

    /* Il fade e' partito: allo scadere dell'attesa si cede lo schermo al
     * viewer del gioco. La lingua va scritta in gLinkPlayers[1] PRIMA:
     * ShowTrainerCardInLink la legge da li' per il font, e a 0 la scheda
     * uscirebbe con la resa giapponese. */
    if (sCardShowWait)'''

RETURN_TICK_ANCHOR = '''    }

    /* Qui, non nell'IRQ: creare uno sprite e caricarne la grafica passa da
     * CpuCopy16, cioe' da una SWI, e una SWI dentro l'handler IRQ mentre il'''
RETURN_TICK_INSERT = '''    }

    /* CUBHMA_REMOTE_INTERACTION_MENU: after Trainer Card, return to the action list,
     * not to Emerald's START menu. We wait for the viewer to leave the field and
     * then for CB2_ReturnToField to restore the overworld. */
    RemoteMenuReturnTick();

    /* Qui, non nell'IRQ: creare uno sprite e caricarne la grafica passa da
     * CpuCopy16, cioe' da una SWI, e una SWI dentro l'handler IRQ mentre il'''

def replace_once(text: str, old: str, new: str, label: str) -> tuple[str, bool]:
    count = text.count(old)
    if count == 0:
        if new in text:
            return text, False
        raise ValueError(f"Could not find the expected {label} anchor. No files changed.")
    if count != 1:
        raise ValueError(f"Expected one {label} anchor, found {count}. No files changed.")
    return text.replace(old, new, 1), True

def backup_and_write(path: Path, content: str) -> None:
    backup = Path(str(path) + ".pre-interaction-menu.bak")
    if not backup.exists():
        shutil.copy2(path, backup)
    path.write_text(content, encoding="utf-8", newline="\n")

def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/patch_remote_interaction_menu.py <path-to-third_party/gen3-poke-multiplayer>",
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

        if "CUBHMA_REMOTE_CARD_RETURN_FIX" not in source or "ADDR_CB2_ReturnToField | 1u" not in source:
            raise ValueError("Run tools/fix_remote_card_return.py first, then rerun this script.")

        # Build both replacements in memory first; no partial writes.
        if GEN_MARKER in gen:
            if all(name in gen for name in (
                '"LoadMessageBoxAndBorderGfx"', '"AddStartMenuWindow"',
                '"Menu_ProcessInputNoWrap"', '"RemoveStartMenuWindow"',
            )):
                gen_changed = False
                new_gen = gen
            else:
                raise ValueError("gen_syms.py has a partial interaction-menu patch; inspect it manually.")
        else:
            new_gen, gen_changed = replace_once(
                gen, GEN_ANCHOR, GEN_INSERT, "symbol-generator function table"
            )
            new_gen = new_gen.replace(
                'FUNCTIONS = {\n',
                'FUNCTIONS = {\n    ' + GEN_MARKER + '\n',
                1,
            )

        if MAIN_MARKER in source:
            required = (
                "static void RemoteInteractionMenuTick(void)",
                "static void RemoteMenuReturnTick(void)",
                "ADDR_Menu_ProcessInputNoWrap",
            )
            if all(item in source for item in required):
                main_changed = False
                new_main = source
            else:
                raise ValueError("main.c has a partial interaction-menu patch; inspect it manually.")
        else:
            new_main, _ = replace_once(source, GLOBAL_ANCHOR, GLOBAL_INSERT, "Trainer Card state")
            new_main, _ = replace_once(new_main, CALLBACK_ANCHOR, CALLBACK_INSERT, "OverworldTick forward declaration")
            new_main, _ = replace_once(new_main, A_ANCHOR, A_REPLACEMENT, "A-button interaction block")
            new_main, _ = replace_once(new_main, COMMENT_OLD, COMMENT_NEW, "old direct-card comment")
            new_main, _ = replace_once(new_main, CARD_IF_OLD, CARD_IF_NEW, "direct Trainer Card trigger")
            new_main, _ = replace_once(new_main, MENU_TICK_ANCHOR, MENU_TICK_INSERT, "interaction menu tick insertion")
            new_main, _ = replace_once(new_main, RETURN_TICK_ANCHOR, RETURN_TICK_INSERT, "return-to-menu tick insertion")
            # Mark the source's first inserted helper block for repeat-safe detection.
            new_main = new_main.replace(
                "static void OverworldTick(void);\n\n/* CUBHMA_REMOTE_INTERACTION_MENU",
                "static void OverworldTick(void);\n\n/* CUBHMA_REMOTE_INTERACTION_MENU",
                1,
            )
            main_changed = True

        if gen_changed:
            backup_and_write(gen_path, new_gen)
        if main_changed:
            backup_and_write(main_path, new_main)

    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("Remote interaction menu patch prepared:")
    print(f"  tools/gen_syms.py: {'patched' if gen_changed else 'already patched'}")
    print(f"  payload/main.c:    {'patched' if main_changed else 'already patched'}")
    print("Backups use the suffix .pre-interaction-menu.bak.")
    print("Next, rebuild the native-link test ROMs with prepare_native_link_roms.ps1.")
    print("The menu UI is added; Trade and Battle remain placeholders until their protocols are implemented.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
